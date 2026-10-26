import hashlib
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Any, Final
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import Clock
from motionile.engine.ai.job_options import JobOptions, JobStatus
from motionile.engine.ai.ports import (
    CompositionIssue,
    EventPayload,
    JobEventDraft,
    JobSnapshot,
    ParentContext,
    SceneAttemptKind,
    SceneRecord,
    StoredStoryboard,
    StoryboardOrigin,
)
from motionile.engine.ai.scenes.models import SceneModule
from motionile.engine.ai.storyboard import Storyboard
from motionile.engine.audio.narration_models import NarrationDocument, NarrationScene, NarrationWord
from motionile.modules.credits import UsageEntry, record_usage
from motionile.modules.generation.event_payloads import sanitize_payload
from motionile.modules.generation.exceptions import JobNotFoundError
from motionile.modules.generation.job_events import JobEvents, JobMessage
from motionile.modules.generation.models import Job, Scene
from motionile.modules.generation.models import Storyboard as StoryboardRow
from motionile.modules.generation.pipeline_repository import PipelineStorage, SceneUpsert, SqlPipelineRepository
from motionile.modules.generation.repository import NewJobEvent, NewStoryboard, sources_for
from motionile.modules.generation.service import GenerationService
from motionile.modules.generation.views import job_source

type Transaction = Callable[[], AbstractAsyncContextManager[AsyncSession]]

MAX_VERSION_ATTEMPTS: Final = 5
CHECKSUM_CHARS: Final = 16
RENDER_USAGE_STAGE: Final = "render"
RENDER_USAGE_PROVIDER: Final = "motionile"


class SceneRowMissingError(LookupError):
    def __init__(self, scene_id: str) -> None:
        super().__init__(f"the scene {scene_id} has no row for the approved storyboard")


class StoryboardNotApprovedError(LookupError):
    def __init__(self) -> None:
        super().__init__("the job has no approved storyboard")


class StoryboardVersionRaceError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("could not reserve a storyboard version")


def module_checksum(module: SceneModule) -> str:
    return hashlib.sha256(module.model_dump_json(by_alias=True).encode("utf-8")).hexdigest()[:CHECKSUM_CHARS]


def stored(row: StoryboardRow) -> StoredStoryboard:
    return StoredStoryboard(
        id=row.id,
        version=row.version,
        content=Storyboard.model_validate(row.content),
        approved=row.approved_at is not None,
    )


def narration_scene(scene: Scene, start_ms: int, duration_ms: int) -> NarrationScene:
    words = tuple(NarrationWord.model_validate(word) for word in scene.word_timestamps or [])
    return NarrationScene(
        id=scene.scene_key,
        index=scene.position,
        start_ms=start_ms,
        duration_ms=duration_ms,
        text=scene.narration,
        words=words,
    )


def narration_from(rows: Sequence[Scene], expected: int) -> NarrationDocument | None:
    if len(rows) != expected or any(row.actual_duration_ms is None or row.word_timestamps is None for row in rows):
        return None
    scenes: list[NarrationScene] = []
    cursor = 0
    for row in rows:
        duration = row.actual_duration_ms or 0
        scenes.append(narration_scene(row, cursor, duration))
        cursor += duration
    return NarrationDocument(total_duration_ms=cursor, scenes=tuple(scenes))


def record_of(row: Scene) -> SceneRecord:
    return SceneRecord(
        scene_id=row.scene_key,
        position=row.position,
        module=SceneModule.model_validate(row.module) if row.module is not None else None,
        attempts=row.repair_attempts,
        is_fallback=row.is_fallback,
    )


class SqlPipelineStore:
    def __init__(
        self,
        transaction: Transaction,
        service: GenerationService,
        events: JobEvents,
        clock: Clock,
        repository: Callable[[AsyncSession, JobEvents], PipelineStorage] = SqlPipelineRepository,
    ) -> None:
        self._transaction = transaction
        self._service = service
        self._events = events
        self._clock = clock
        self._repository = repository

    def _repo(self, session: AsyncSession) -> PipelineStorage:
        return self._repository(session, self._events)

    async def snapshot(self, job_id: UUID) -> JobSnapshot:
        async with self._transaction() as session:
            repo = self._repo(session)
            job = await repo.get_for_pipeline(job_id)
            if job is None:
                raise JobNotFoundError
            topic = await repo.topic_of(job.topic_id) if job.topic_id is not None else None
            preferences = await repo.preferences_of(job.user_id)
            parent = await self._parent(repo, job)
        return JobSnapshot(
            id=job.id,
            user_id=job.user_id,
            source=job_source(job.source),
            query=job.query,
            topic=topic,
            options=JobOptions.model_validate(job.options),
            status=JobStatus(job.status),
            cancel_requested=job.cancel_requested_at is not None,
            preferences=preferences,
            parent=parent,
            render_id=job.render_id,
        )

    async def _parent(self, repo: PipelineStorage, job: Job) -> ParentContext | None:
        if job.parent_job_id is None:
            return None
        row = await repo.latest_approved_storyboard(job.parent_job_id)
        if row is None:
            return None
        return ParentContext(job_id=job.parent_job_id, storyboard=Storyboard.model_validate(row.content))

    async def transition(self, job_id: UUID, to: JobStatus, *, stage: str) -> bool:
        async with self._transaction() as session:
            sources = sources_for(to) if to.is_terminal else sources_for(to) | {to}
            return await self._repo(session).move(job_id, to, sources, stage)

    async def emit(self, job_id: UUID, event: JobEventDraft) -> None:
        payload = sanitize_payload(event.type, event.payload)
        if event.persist:
            async with self._transaction() as session:
                repo = self._repo(session)
                await repo.add_event(NewJobEvent(job_id, event.type, event.stage, payload))
                await repo.touch(job_id)
            return
        message = JobMessage(id=None, type=event.type, stage=event.stage, payload=payload, at=self._clock.now())
        await self._events.publish(job_id, message)

    async def save_storyboard(self, job_id: UUID, storyboard: Storyboard, origin: StoryboardOrigin) -> StoredStoryboard:
        content: dict[str, Any] = storyboard.model_dump(mode="json", by_alias=True)
        async with self._transaction() as session:
            repo = self._repo(session)
            for _ in range(MAX_VERSION_ATTEMPTS):
                latest = await repo.storyboard_pipeline(job_id)
                version = (latest.version if latest is not None else 0) + 1
                row = await repo.insert_storyboard(NewStoryboard(job_id, version, origin.value, content))
                if row is not None:
                    return stored(row)
        raise StoryboardVersionRaceError

    async def latest_storyboard(self, job_id: UUID) -> StoredStoryboard | None:
        async with self._transaction() as session:
            row = await self._repo(session).storyboard_pipeline(job_id)
        return stored(row) if row is not None else None

    async def approved_storyboard(self, job_id: UUID) -> StoredStoryboard | None:
        async with self._transaction() as session:
            row = await self._repo(session).latest_approved_storyboard(job_id)
        return stored(row) if row is not None else None

    async def approve_storyboard(self, job_id: UUID, storyboard_id: UUID) -> None:
        async with self._transaction() as session:
            await self._repo(session).approve(storyboard_id, job_id, self._clock.now())

    async def save_narration(self, job_id: UUID, narration: NarrationDocument) -> None:
        async with self._transaction() as session:
            repo = self._repo(session)
            row = await repo.latest_approved_storyboard(job_id)
            if row is None:
                raise StoryboardNotApprovedError
            board = Storyboard.model_validate(row.content)
            planned = {scene.id: scene for scene in board.scenes}
            upserts = [
                SceneUpsert(
                    scene_key=spoken.id,
                    position=planned[spoken.id].position,
                    narration=spoken.text,
                    visual_brief=planned[spoken.id].visual_brief,
                    target_duration_ms=planned[spoken.id].target_duration_ms,
                    actual_duration_ms=spoken.duration_ms,
                    word_timestamps=[word.model_dump(mode="json", by_alias=True) for word in spoken.words],
                )
                for spoken in narration.scenes
            ]
            await repo.upsert_scenes(row.id, upserts)

    async def narration(self, job_id: UUID) -> NarrationDocument | None:
        async with self._transaction() as session:
            repo = self._repo(session)
            row = await repo.latest_approved_storyboard(job_id)
            if row is None:
                return None
            scenes = await repo.scenes_of(row.id)
        return narration_from(scenes, len(Storyboard.model_validate(row.content).scenes))

    async def save_scene_module(
        self, job_id: UUID, module: SceneModule, kind: SceneAttemptKind, issues: Sequence[CompositionIssue]
    ) -> None:
        async with self._transaction() as session:
            repo = self._repo(session)
            board = await repo.latest_approved_storyboard(job_id)
            if board is None:
                raise StoryboardNotApprovedError
            scene = await repo.scene_for_update(board.id, module.scene_id)
            if scene is None:
                raise SceneRowMissingError(module.scene_id)
            entry: dict[str, JsonValue] = {
                "attempt": len(scene.attempt_log) + 1,
                "kind": kind.value,
                "issueCodes": list[JsonValue](sorted({issue.code for issue in issues})),
                "checksum": module_checksum(module),
            }
            scene.module = module.model_dump(mode="json", by_alias=True)
            scene.status = "generated"
            scene.attempt_log = [*scene.attempt_log, entry]
            if kind is SceneAttemptKind.REPAIR:
                scene.repair_attempts += 1
            if kind is SceneAttemptKind.FALLBACK:
                scene.is_fallback = True
            await session.flush()

    async def scenes(self, job_id: UUID) -> list[SceneRecord]:
        async with self._transaction() as session:
            repo = self._repo(session)
            board = await repo.latest_approved_storyboard(job_id)
            rows = await repo.scenes_of(board.id) if board is not None else []
        return [record_of(row) for row in rows]

    async def save_reports(self, job_id: UUID, *, validation: EventPayload, review: EventPayload) -> None:
        if not validation and not review:
            return
        async with self._transaction() as session:
            repo = self._repo(session)
            if validation:
                await repo.merge_report(job_id, "validation", validation)
            if review:
                await repo.merge_report(job_id, "review", review)

    async def attach_render(self, job_id: UUID, render_id: UUID) -> None:
        async with self._transaction() as session:
            await self._repo(session).attach_render(job_id, render_id)

    async def fail(self, job_id: UUID, code: str, message: str) -> None:
        async with self._transaction() as session:
            await self._service.fail_job(session, job_id, code, message)

    async def complete(self, job_id: UUID, *, final_duration_ms: int) -> None:
        async with self._transaction() as session:
            await self._record_render_usage(session, job_id)
            await self._service.complete_job(session, job_id, final_duration_ms)

    async def finish_cancellation(self, job_id: UUID) -> None:
        async with self._transaction() as session:
            await self._service.finish_cancellation(session, job_id)

    async def _record_render_usage(self, session: AsyncSession, job_id: UUID) -> None:
        repo = self._repo(session)
        job = await repo.get_for_pipeline(job_id)
        if job is None or job.render_id is None:
            return
        timings = await repo.render_timings(job.render_id)
        milliseconds = sum(value for value in timings.values() if isinstance(value, int))
        if milliseconds <= 0:
            return
        await record_usage(
            session,
            UsageEntry(
                user_id=job.user_id,
                stage=RENDER_USAGE_STAGE,
                provider=RENDER_USAGE_PROVIDER,
                key=f"{RENDER_USAGE_STAGE}:{job_id}",
                render_ms=milliseconds,
                job_id=job_id,
            ),
        )
