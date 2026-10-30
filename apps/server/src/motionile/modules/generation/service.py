import re
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.alerts import raise_alert
from motionile.core.clock import Clock
from motionile.core.events import EventBus
from motionile.core.ids import new_id
from motionile.core.pagination import Cursor
from motionile.engine.ai.guardrails import GuardResult
from motionile.engine.ai.job_options import JobOptions, JobStatus, RevisionRequest
from motionile.engine.ai.ports import JobSource
from motionile.engine.ai.storyboard import Storyboard
from motionile.modules.audit import ActorType, AuditContext, AuditEvent
from motionile.modules.audit import record as record_audit
from motionile.modules.credits import (
    CreditsService,
    InsufficientCreditsError,
    ReservationNotActiveError,
    ReservationNotFoundError,
    ReservationView,
    ReserveCommand,
)
from motionile.modules.generation.charging import charge_for
from motionile.modules.generation.edits import changed_texts, instructions_digest
from motionile.modules.generation.event_payloads import sanitize_payload
from motionile.modules.generation.events import JobCompleted
from motionile.modules.generation.exceptions import (
    InputRefusedError,
    JobInsufficientCreditsError,
    JobNotCancellableError,
    JobNotDeletableError,
    JobNotFoundError,
    JobNotRevisableError,
    JobOptionsInvalidError,
    StoryboardInvalidError,
    StoryboardNotEditableError,
    StoryboardNotFoundError,
    StoryboardVersionConflictError,
    TooManyActiveJobsError,
    TopicNotFoundError,
)
from motionile.modules.generation.models import Job
from motionile.modules.generation.models import Storyboard as StoryboardRow
from motionile.modules.generation.options import OptionInputs, OptionResolver, estimate_for, with_revision
from motionile.modules.generation.ports import (
    CheckpointPurger,
    EditGuard,
    JobDispatch,
    RenderCleanup,
    ResumeKind,
    TopicLookup,
)
from motionile.modules.generation.repository import (
    JobFilter,
    JobStore,
    NewJob,
    NewJobEvent,
    NewStoryboard,
    SqlJobRepository,
    sources_for,
)
from motionile.modules.generation.runtime_settings import JOB_RESERVATION_TTL, RuntimeSettings
from motionile.modules.generation.schemas import (
    ApproveRequest,
    ChargingParametersView,
    EstimateRequest,
    EstimateView,
    JobCreateRequest,
    JobView,
    RegenerateRequest,
    ReviseRequest,
    StoryboardUpdateRequest,
    StoryboardView,
)
from motionile.modules.generation.views import (
    issue_errors,
    job_source,
    job_view,
    storyboard_issues,
    storyboard_view,
)

JOB_REF_TYPE = "job"
AUDIT_TARGET = "job"
ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,59}$")
ERROR_MESSAGE_LIMIT = 2_000
CANCELLED_BY_USER = "cancelled_by_user"
RESERVATION_LOST_ALERT = "generation.reservation_lost"
IMMEDIATE_CANCEL_SOURCES = frozenset({JobStatus.QUEUED, JobStatus.AWAITING_APPROVAL})

type AuditRecorder = Callable[[AsyncSession, AuditEvent, AuditContext | None], Awaitable[UUID]]
type StoreFactory = Callable[[AsyncSession], JobStore]
type Transaction = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def create_key(client_key: str) -> str:
    return f"create:{client_key}"


def revise_key(parent_id: UUID, client_key: str) -> str:
    return f"revise:{parent_id}:{client_key}"


def reserve_key(job_id: UUID) -> str:
    return f"job:{job_id}:reserve"


def commit_key(job_id: UUID) -> str:
    return f"job:{job_id}:commit"


def release_key(job_id: UUID) -> str:
    return f"job:{job_id}:release"


@dataclass(frozen=True, slots=True)
class JobsPage:
    items: list[JobView]
    next_cursor: Cursor | None


@dataclass(frozen=True, slots=True)
class GenerationDeps:
    credits: CreditsService
    settings: RuntimeSettings
    options: OptionResolver
    topics: TopicLookup
    edit_guard: EditGuard
    renders: RenderCleanup
    checkpoints: CheckpointPurger
    clock: Clock
    events: EventBus
    dispatch: JobDispatch
    store_factory: StoreFactory = SqlJobRepository
    audit: AuditRecorder = record_audit


@dataclass(frozen=True, slots=True)
class EditPreview:
    unchanged: StoryboardView | None
    texts: list[str]


@dataclass(frozen=True, slots=True)
class JobDraft:
    user_id: UUID
    source: JobSource
    topic_id: UUID | None
    parent_job_id: UUID | None
    query: str
    options: JobOptions
    idempotency_key: str


def require_allowed(result: GuardResult) -> None:
    if not result.allowed and result.code is not None:
        raise InputRefusedError(result.code)


class GenerationService:
    def __init__(self, deps: GenerationDeps) -> None:
        self._deps = deps

    def _store(self, session: AsyncSession) -> JobStore:
        return self._deps.store_factory(session)

    async def estimate(self, session: AsyncSession, user_id: UUID, request: EstimateRequest) -> EstimateView:
        options = await self._deps.options.resolve(session, user_id, OptionInputs.from_request(request.options))
        parameters = await self._deps.settings.charging(session)
        amount = estimate_for(parameters, options)
        wallet = await self._deps.credits.wallet(session, user_id)
        return EstimateView(
            credits=amount,
            available_credits=wallet.available,
            affordable=wallet.available >= amount,
            seconds=options.duration_seconds,
            aspect_count=len(options.aspects),
            cloned_voice=options.voice_is_cloned,
            parameters=ChargingParametersView(
                base_credits=parameters.base_credits,
                credits_per_second=parameters.credits_per_second,
                extra_aspect_percent=parameters.extra_aspect_percent,
                cloned_voice_premium=parameters.cloned_voice_premium,
            ),
        )

    async def create(
        self,
        session: AsyncSession,
        user_id: UUID,
        request: JobCreateRequest,
        idempotency_key: str,
        context: AuditContext | None = None,
    ) -> JobView:
        store = self._store(session)
        scoped_key = create_key(idempotency_key)
        replayed = await store.get_by_key(user_id, scoped_key)
        if replayed is not None:
            return await self._view(store, replayed)
        source, topic_id, query = await self._source(session, request)
        options = await self._deps.options.resolve(session, user_id, OptionInputs.from_request(request.options))
        draft = JobDraft(user_id, source, topic_id, None, query, options, scoped_key)
        return await self._admit(session, store, draft, context)

    async def revise(  # noqa: PLR0913, PLR0917
        self,
        transaction: Transaction,
        user_id: UUID,
        parent_id: UUID,
        request: ReviseRequest,
        idempotency_key: str,
        context: AuditContext | None = None,
    ) -> JobView:
        scoped_key = revise_key(parent_id, idempotency_key)
        async with transaction() as session:
            store = self._store(session)
            replayed = await store.get_by_key(user_id, scoped_key)
            if replayed is not None:
                return await self._view(store, replayed)
            await self._revisable_parent(store, user_id, parent_id, request)
        require_allowed(await self._deps.edit_guard.check_instructions(user_id, parent_id, request.instructions))
        async with transaction() as session:
            store = self._store(session)
            parent = await self._revisable_parent(store, user_id, parent_id, request)
            base = JobOptions.model_validate(parent.options).model_copy(update={"revision": None})
            options = await self._deps.options.resolve(
                session, user_id, OptionInputs.from_overrides(request.options), base
            )
            revised = with_revision(
                options, RevisionRequest(instructions=request.instructions, scene_ids=request.scene_ids)
            )
            draft = JobDraft(
                user_id=user_id,
                source=job_source(parent.source),
                topic_id=parent.topic_id,
                parent_job_id=parent.id,
                query=parent.query,
                options=revised,
                idempotency_key=scoped_key,
            )
            return await self._admit(session, store, draft, context)

    async def get(self, session: AsyncSession, user_id: UUID, job_id: UUID) -> JobView:
        store = self._store(session)
        return await self._view(store, await self._owned(store, user_id, job_id))

    async def list_jobs(
        self, session: AsyncSession, user_id: UUID, job_filter: JobFilter, cursor: Cursor | None, limit: int
    ) -> JobsPage:
        store = self._store(session)
        rows = await store.page(user_id, job_filter, cursor, limit)
        shown = rows[:limit]
        next_cursor = Cursor(shown[-1].created_at, shown[-1].id) if len(rows) > limit and shown else None
        completed = [job.id for job in shown if job.status == JobStatus.COMPLETED.value]
        fallbacks = await store.fallback_scene_keys(completed)
        return JobsPage([job_view(job, fallbacks.get(job.id, ())) for job in shown], next_cursor)

    async def storyboard(self, session: AsyncSession, user_id: UUID, job_id: UUID) -> StoryboardView:
        store = self._store(session)
        job = await self._owned(store, user_id, job_id)
        row = await store.latest_storyboard(user_id, job_id)
        if row is None:
            raise StoryboardNotFoundError
        limits = await self._deps.settings.storyboard_limits(session)
        return storyboard_view(row, JobOptions.model_validate(job.options), limits)

    async def update_storyboard(
        self, transaction: Transaction, user_id: UUID, job_id: UUID, request: StoryboardUpdateRequest
    ) -> StoryboardView:
        async with transaction() as session:
            preview = await self._preview_edit(session, user_id, job_id, request)
        if preview.unchanged is not None:
            return preview.unchanged
        if preview.texts:
            require_allowed(await self._deps.edit_guard.check_edit(user_id, job_id, preview.texts))
        async with transaction() as session:
            return await self._save_edit(session, user_id, job_id, request)

    async def regenerate(
        self, transaction: Transaction, user_id: UUID, job_id: UUID, request: RegenerateRequest
    ) -> JobView:
        async with transaction() as session:
            self._require_awaiting_approval(await self._owned(self._store(session), user_id, job_id))
        require_allowed(await self._deps.edit_guard.check_instructions(user_id, job_id, request.instructions))
        async with transaction() as session:
            return await self._request_regeneration(session, user_id, job_id, request)

    async def approve(
        self,
        session: AsyncSession,
        user_id: UUID,
        job_id: UUID,
        request: ApproveRequest,
        context: AuditContext | None = None,
    ) -> JobView:
        store = self._store(session)
        job = await self._locked(store, user_id, job_id)
        latest = await self._editable_storyboard(store, user_id, job, request.expected_version)
        if not await store.approve_storyboard(latest.id, user_id, self._deps.clock.now()):
            raise StoryboardNotEditableError
        await store.add_event(
            NewJobEvent(job_id, "approval.granted", stage="approval", payload={"version": latest.version})
        )
        await self._audit(session, user_id, "job.approved", job_id, {"version": latest.version}, context)
        self._deps.dispatch.resume(session, job_id, ResumeKind.APPROVE, None)
        return await self._view(store, job)

    async def cancel(
        self, session: AsyncSession, user_id: UUID, job_id: UUID, context: AuditContext | None = None
    ) -> JobView:
        store = self._store(session)
        job = await self._locked(store, user_id, job_id)
        status = JobStatus(job.status)
        if status.is_terminal:
            return await self._view(store, job)
        now = self._deps.clock.now()
        if await self._cancels_at_once(store, user_id, job):
            cancelled = await store.transition(
                job_id,
                JobStatus.CANCELLED,
                IMMEDIATE_CANCEL_SOURCES,
                {"cancel_requested_at": now, "completed_at": now},
            )
            if cancelled is None:
                raise JobNotCancellableError
            await self._record_cancellation(session, store, cancelled, user_id, context)
            return await self._view(store, cancelled)
        requested = await store.request_cancel(job_id, now)
        if requested is None:
            raise JobNotCancellableError
        await store.add_event(NewJobEvent(job_id, "job.cancel_requested", stage=requested.current_stage))
        await self._audit(session, user_id, "job.cancel_requested", job_id, {}, context)
        return await self._view(store, requested)

    async def delete(
        self, session: AsyncSession, user_id: UUID, job_id: UUID, context: AuditContext | None = None
    ) -> None:
        store = self._store(session)
        job = await self._locked(store, user_id, job_id)
        if not JobStatus(job.status).is_terminal:
            raise JobNotDeletableError
        if job.render_id is not None:
            await self._deps.renders.delete_render(session, user_id, job.render_id)
        await store.delete(user_id, job_id)
        await self._deps.checkpoints.purge([job_id])
        await self._audit(session, user_id, "job.deleted", job_id, {"status": job.status}, context)

    async def fail_job(self, session: AsyncSession, job_id: UUID, code: str, message: str) -> bool:
        if ERROR_CODE_PATTERN.fullmatch(code) is None:
            raise ValueError(f"{code!r} is not a valid job error code")
        store = self._store(session)
        job = await store.get_for_pipeline(job_id, lock=True)
        if job is None:
            return False
        failed = await store.transition(
            job_id,
            JobStatus.FAILED,
            sources_for(JobStatus.FAILED),
            {
                "error_code": code,
                "error_message": message[:ERROR_MESSAGE_LIMIT],
                "completed_at": self._deps.clock.now(),
            },
        )
        if failed is None:
            return False
        released = await self._release(session, failed)
        await store.add_event(
            NewJobEvent(
                job_id,
                "job.failed",
                stage=failed.current_stage,
                payload=sanitize_payload(
                    "job.failed", {"code": code, "message": message[:ERROR_MESSAGE_LIMIT], "creditsReleased": released}
                ),
            )
        )
        return True

    async def complete_job(self, session: AsyncSession, job_id: UUID, final_duration_ms: int) -> int | None:
        store = self._store(session)
        job = await store.get_for_pipeline(job_id, lock=True)
        if job is None or JobStatus(job.status) not in sources_for(JobStatus.COMPLETED):
            return None
        reservation = await self._deps.credits.active_reservation(
            session, job.user_id, JOB_REF_TYPE, job.id, for_update=True
        )
        charged = await self._settle(session, job, reservation, final_duration_ms)
        completed = await store.transition(
            job_id,
            JobStatus.COMPLETED,
            sources_for(JobStatus.COMPLETED),
            {"credits_charged": charged, "completed_at": self._deps.clock.now()},
        )
        if completed is None:
            return None
        fallbacks = (await store.fallback_scene_keys([job_id])).get(job_id, [])
        await store.add_event(
            NewJobEvent(
                job_id,
                "job.completed",
                stage=completed.current_stage,
                payload={"creditsCharged": charged, "durationMs": final_duration_ms, "fallbackSceneIds": fallbacks},
            )
        )
        self._deps.events.publish_after_commit(
            session,
            JobCompleted(job_id=job.id, user_id=job.user_id, duration_ms=final_duration_ms, credits_charged=charged),
        )
        return charged

    async def has_active_reservation(self, session: AsyncSession, job_id: UUID) -> bool:
        job = await self._store(session).get_for_pipeline(job_id)
        if job is None:
            return False
        reservation = await self._deps.credits.active_reservation(session, job.user_id, JOB_REF_TYPE, job.id)
        return reservation is not None

    async def finish_cancellation(self, session: AsyncSession, job_id: UUID, reason: str = CANCELLED_BY_USER) -> bool:
        store = self._store(session)
        job = await store.get_for_pipeline(job_id, lock=True)
        if job is None:
            return False
        cancelled = await store.transition(
            job_id,
            JobStatus.CANCELLED,
            sources_for(JobStatus.CANCELLED),
            {"completed_at": self._deps.clock.now()},
        )
        if cancelled is None:
            return False
        await self._record_cancellation(session, store, cancelled, cancelled.user_id, None, reason)
        return True

    async def _preview_edit(
        self, session: AsyncSession, user_id: UUID, job_id: UUID, request: StoryboardUpdateRequest
    ) -> EditPreview:
        store = self._store(session)
        job = await self._owned(store, user_id, job_id)
        latest = await self._editable_storyboard(store, user_id, job, request.expected_version)
        previous = Storyboard.model_validate(latest.content)
        options = JobOptions.model_validate(job.options)
        limits = await self._deps.settings.storyboard_limits(session)
        issues = storyboard_issues(request.content, options, limits)
        if issues:
            raise StoryboardInvalidError(issue_errors(request.content, issues))
        if request.content == previous:
            return EditPreview(storyboard_view(latest, options, limits), [])
        return EditPreview(None, changed_texts(previous, request.content))

    async def _save_edit(
        self, session: AsyncSession, user_id: UUID, job_id: UUID, request: StoryboardUpdateRequest
    ) -> StoryboardView:
        store = self._store(session)
        locked = await self._locked(store, user_id, job_id)
        current = await self._editable_storyboard(store, user_id, locked, request.expected_version)
        options = JobOptions.model_validate(locked.options)
        limits = await self._deps.settings.storyboard_limits(session)
        saved = await store.insert_storyboard(
            NewStoryboard(
                job_id=job_id,
                version=current.version + 1,
                origin="user",
                content=request.content.model_dump(mode="json", by_alias=True),
            )
        )
        if saved is None:
            raise StoryboardVersionConflictError(current.version + 1)
        await store.add_event(
            NewJobEvent(
                job_id, "storyboard.updated", stage="approval", payload={"version": saved.version, "origin": "user"}
            )
        )
        return storyboard_view(saved, options, limits)

    async def _request_regeneration(
        self, session: AsyncSession, user_id: UUID, job_id: UUID, request: RegenerateRequest
    ) -> JobView:
        store = self._store(session)
        locked = await self._locked(store, user_id, job_id)
        self._require_awaiting_approval(locked)
        latest = await store.latest_storyboard(user_id, job_id)
        if latest is not None and latest.approved_at is not None:
            raise StoryboardNotEditableError
        moved = await store.transition(
            job_id, JobStatus.PLANNING, {JobStatus.AWAITING_APPROVAL}, {"current_stage": "plan"}
        )
        if moved is None:
            raise StoryboardNotEditableError
        await store.add_event(
            NewJobEvent(
                job_id,
                "storyboard.regenerate_requested",
                stage="approval",
                payload={
                    "length": len(request.instructions),
                    "digest": instructions_digest(request.instructions),
                },
            )
        )
        self._deps.dispatch.resume(session, job_id, ResumeKind.REGENERATE, request.instructions)
        return await self._view(store, moved)

    async def _revisable_parent(self, store: JobStore, user_id: UUID, parent_id: UUID, request: ReviseRequest) -> Job:
        parent = await self._owned(store, user_id, parent_id)
        if parent.status != JobStatus.COMPLETED.value:
            raise JobNotRevisableError
        await self._check_scene_ids(store, user_id, parent, request)
        return parent

    async def _source(self, session: AsyncSession, request: JobCreateRequest) -> tuple[JobSource, UUID | None, str]:
        if request.topic_id is not None:
            topic = await self._deps.topics.published(session, request.topic_id)
            if topic is None:
                raise TopicNotFoundError
            return "catalog", topic.id, topic.title
        if request.query is None:
            raise JobOptionsInvalidError("Send a topicId or a query.")
        return "query", None, request.query

    async def _check_scene_ids(self, store: JobStore, user_id: UUID, parent: Job, request: ReviseRequest) -> None:
        if not request.scene_ids:
            return
        row = await store.latest_storyboard(user_id, parent.id)
        known: set[str] = set()
        if row is not None:
            known.update(scene.id for scene in Storyboard.model_validate(row.content).scenes)
        unknown = sorted(set(request.scene_ids) - known)
        if unknown:
            raise JobOptionsInvalidError(f"The video has no scenes {unknown}.")

    async def _admit(
        self, session: AsyncSession, store: JobStore, draft: JobDraft, context: AuditContext | None
    ) -> JobView:
        await store.lock_creation(draft.user_id)
        replayed = await store.get_by_key(draft.user_id, draft.idempotency_key)
        if replayed is not None:
            return await self._view(store, replayed)
        limit = await self._deps.settings.max_active_jobs(session)
        if await store.count_active(draft.user_id) >= limit:
            raise TooManyActiveJobsError(limit)
        parameters = await self._deps.settings.charging(session)
        amount = estimate_for(parameters, draft.options)
        job = await store.insert(
            NewJob(
                id=new_id(),
                user_id=draft.user_id,
                source=draft.source,
                topic_id=draft.topic_id,
                parent_job_id=draft.parent_job_id,
                query=draft.query,
                options=draft.options.model_dump(mode="json", by_alias=True),
                credits_estimated=amount,
                credits_reserved=amount,
                idempotency_key=draft.idempotency_key,
            )
        )
        if amount > 0:
            await self._reserve(session, job, amount)
        await store.add_event(NewJobEvent(job.id, "job.created", payload={"creditsReserved": amount}))
        metadata: dict[str, Any] = {"source": draft.source, "creditsReserved": amount}
        if draft.parent_job_id is not None:
            metadata["parentJobId"] = str(draft.parent_job_id)
        await self._audit(session, draft.user_id, "job.created", job.id, metadata, context)
        self._deps.dispatch.run(session, job.id)
        return job_view(job)

    async def _reserve(self, session: AsyncSession, job: Job, amount: int) -> None:
        try:
            await self._deps.credits.reserve(
                session,
                ReserveCommand(job.user_id, amount, JOB_REF_TYPE, job.id, reserve_key(job.id), JOB_RESERVATION_TTL),
            )
        except InsufficientCreditsError as error:
            raise JobInsufficientCreditsError(available=error.available, required=error.required) from None

    async def _settle(
        self, session: AsyncSession, job: Job, reservation: ReservationView | None, final_duration_ms: int
    ) -> int:
        if reservation is None:
            if job.credits_reserved > 0:
                raise_alert(RESERVATION_LOST_ALERT, job_id=str(job.id))
            return 0
        charged = await self._charge(session, job, final_duration_ms, reservation.amount)
        try:
            await self._deps.credits.commit(session, reservation.id, charged, commit_key(job.id))
        except ReservationNotActiveError:
            raise_alert(RESERVATION_LOST_ALERT, job_id=str(job.id))
            return 0
        return charged

    async def _charge(self, session: AsyncSession, job: Job, final_duration_ms: int, reserved: int) -> int:
        if reserved <= 0:
            return 0
        parameters = await self._deps.settings.charging(session)
        options = JobOptions.model_validate(job.options)
        return charge_for(parameters, final_duration_ms, len(options.aspects), options.voice_is_cloned, reserved)

    async def _release(self, session: AsyncSession, job: Job) -> int:
        reservation = await self._deps.credits.active_reservation(session, job.user_id, JOB_REF_TYPE, job.id)
        if reservation is None:
            return 0
        try:
            await self._deps.credits.release(session, reservation.id, release_key(job.id))
        except (ReservationNotActiveError, ReservationNotFoundError):
            return 0
        return reservation.amount

    async def _record_cancellation(  # noqa: PLR0913, PLR0917
        self,
        session: AsyncSession,
        store: JobStore,
        job: Job,
        user_id: UUID,
        context: AuditContext | None,
        reason: str = CANCELLED_BY_USER,
    ) -> None:
        released = await self._release(session, job)
        await store.add_event(
            NewJobEvent(
                job.id,
                "job.cancelled",
                stage=job.current_stage,
                payload={"code": reason, "creditsReleased": released},
            )
        )
        if reason == CANCELLED_BY_USER:
            await self._audit(session, user_id, "job.cancelled", job.id, {"creditsReleased": released}, context)
            return
        await self._audit_system(session, "job.cancelled", job.id, {"creditsReleased": released, "reason": reason})

    async def _cancels_at_once(self, store: JobStore, user_id: UUID, job: Job) -> bool:
        status = JobStatus(job.status)
        if status not in IMMEDIATE_CANCEL_SOURCES:
            return False
        if status is JobStatus.QUEUED:
            return True
        latest = await store.latest_storyboard(user_id, job.id)
        return latest is None or latest.approved_at is None

    async def _editable_storyboard(
        self, store: JobStore, user_id: UUID, job: Job, expected_version: int
    ) -> StoryboardRow:
        self._require_awaiting_approval(job)
        latest = await store.latest_storyboard(user_id, job.id)
        if latest is None:
            raise StoryboardNotFoundError
        if latest.approved_at is not None:
            raise StoryboardNotEditableError
        if latest.version != expected_version:
            raise StoryboardVersionConflictError(latest.version)
        return latest

    @staticmethod
    def _require_awaiting_approval(job: Job) -> None:
        if job.status != JobStatus.AWAITING_APPROVAL.value:
            raise StoryboardNotEditableError

    async def _owned(self, store: JobStore, user_id: UUID, job_id: UUID) -> Job:
        job = await store.get_owned(user_id, job_id)
        if job is None:
            raise JobNotFoundError
        return job

    async def _locked(self, store: JobStore, user_id: UUID, job_id: UUID) -> Job:
        job = await store.get_owned(user_id, job_id, lock=True)
        if job is None:
            raise JobNotFoundError
        return job

    async def _view(self, store: JobStore, job: Job) -> JobView:
        if job.status != JobStatus.COMPLETED.value:
            return job_view(job)
        return job_view(job, (await store.fallback_scene_keys([job.id])).get(job.id, ()))

    async def _audit_system(self, session: AsyncSession, action: str, job_id: UUID, metadata: dict[str, Any]) -> None:
        await self._deps.audit(
            session,
            AuditEvent(
                action=action,
                actor_type=ActorType.SYSTEM,
                target_type=AUDIT_TARGET,
                target_id=str(job_id),
                metadata=metadata,
            ),
            None,
        )

    async def _audit(  # noqa: PLR0913, PLR0917
        self,
        session: AsyncSession,
        user_id: UUID,
        action: str,
        job_id: UUID,
        metadata: dict[str, Any],
        context: AuditContext | None,
    ) -> None:
        await self._deps.audit(
            session,
            AuditEvent(
                action=action,
                actor_type=ActorType.USER,
                actor_user_id=user_id,
                target_type=AUDIT_TARGET,
                target_id=str(job_id),
                metadata=metadata,
            ),
            context,
        )
