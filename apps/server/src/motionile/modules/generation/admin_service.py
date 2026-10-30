from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any, Final, cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import Clock
from motionile.core.pagination import Cursor
from motionile.engine.ai.job_options import JobStatus
from motionile.engine.ai.llm.tracing import job_trace_id, trace_link
from motionile.engine.ai.storyboard import Storyboard
from motionile.modules.audit import ActorType, AuditContext, AuditEvent
from motionile.modules.audit import record as record_audit
from motionile.modules.generation.admin_repository import AdminJobFilter, AdminStore, SqlAdminRepository, UsageTotals
from motionile.modules.generation.admin_schemas import (
    MAX_QUERY_PREVIEW,
    AdminCostView,
    AdminEventView,
    AdminJobDetail,
    AdminJobSummary,
    AdminSceneView,
    AdminStoryboardVersion,
    AnalyticsQuery,
    JobAnalyticsView,
)
from motionile.modules.generation.analytics import (
    fallback_rate,
    overall_success_rate,
    repair_rate,
    resolve_range,
    stage_views,
    zero_filled_days,
)
from motionile.modules.generation.exceptions import JobNotFoundError
from motionile.modules.generation.models import Job, Scene
from motionile.modules.generation.views import job_source, job_view

type AdminStoreFactory = Callable[[AsyncSession], AdminStore]
type AuditRecorder = Callable[[AsyncSession, AuditEvent, AuditContext | None], Awaitable[UUID]]

MESSAGE_KEY: Final = "message"
REVIEW_KEY: Final = "review"
ISSUES_KEY: Final = "issues"
JOB_VIEWED_ACTION: Final = "job.admin_viewed"
JOB_TARGET: Final = "job"


@dataclass(frozen=True, slots=True)
class TraceSettings:
    enabled: bool
    host: str
    project_id: str | None


@dataclass(frozen=True, slots=True)
class AdminJobsResult:
    items: list[AdminJobSummary]
    next_cursor: Cursor | None


def public_reports(reports: Mapping[str, Any]) -> dict[str, JsonValue]:
    cleaned = cast("dict[str, JsonValue]", dict(reports))
    review = cleaned.get(REVIEW_KEY)
    if isinstance(review, dict):
        issues = review.get(ISSUES_KEY)
        stripped = (
            [
                {name: value for name, value in issue.items() if name != MESSAGE_KEY}
                for issue in issues
                if isinstance(issue, dict)
            ]
            if isinstance(issues, list)
            else []
        )
        cleaned[REVIEW_KEY] = {**review, ISSUES_KEY: cast("JsonValue", stripped)}
    return cleaned


def summary_of(job: Job) -> AdminJobSummary:
    return AdminJobSummary(
        id=job.id,
        user_id=job.user_id,
        source=job_source(job.source),
        status=JobStatus(job.status),
        current_stage=job.current_stage,
        error_code=job.error_code,
        query=job.query[:MAX_QUERY_PREVIEW],
        credits_estimated=job.credits_estimated,
        credits_reserved=job.credits_reserved,
        credits_charged=job.credits_charged,
        parent_job_id=job.parent_job_id,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


def scene_view(scene: Scene) -> AdminSceneView:
    return AdminSceneView(
        scene_id=scene.scene_key,
        position=scene.position,
        status=scene.status,
        repair_attempts=scene.repair_attempts,
        is_fallback=scene.is_fallback,
        actual_duration_ms=scene.actual_duration_ms,
        attempt_log=cast("list[dict[str, JsonValue]]", list(scene.attempt_log)),
        error_code=scene.error_code,
    )


def cost_view(usage: UsageTotals, credits_charged: int | None) -> AdminCostView:
    return AdminCostView(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        audio_characters=usage.audio_characters,
        render_ms=usage.render_ms,
        cost_micros_usd=usage.cost_micros_usd,
        usage_records=usage.records,
        credits_charged=credits_charged,
    )


class AdminJobsService:
    def __init__(
        self,
        clock: Clock,
        tracing: TraceSettings,
        store_factory: AdminStoreFactory = SqlAdminRepository,
        audit: AuditRecorder = record_audit,
    ) -> None:
        self._clock = clock
        self._tracing = tracing
        self._store_factory = store_factory
        self._audit = audit

    async def list_jobs(
        self, session: AsyncSession, job_filter: AdminJobFilter, cursor: Cursor | None, limit: int
    ) -> AdminJobsResult:
        rows = await self._store_factory(session).page(job_filter, cursor, limit)
        shown = rows[:limit]
        next_cursor = Cursor(shown[-1].created_at, shown[-1].id) if len(rows) > limit and shown else None
        return AdminJobsResult([summary_of(job) for job in shown], next_cursor)

    async def detail(
        self, session: AsyncSession, admin_id: UUID, job_id: UUID, context: AuditContext | None = None
    ) -> AdminJobDetail:
        store = self._store_factory(session)
        job = await store.job(job_id)
        if job is None:
            raise JobNotFoundError
        await self._audit(
            session,
            AuditEvent(
                action=JOB_VIEWED_ACTION,
                actor_type=ActorType.ADMIN,
                actor_user_id=admin_id,
                target_type=JOB_TARGET,
                target_id=str(job_id),
                metadata={"ownerId": str(job.user_id)},
            ),
            context,
        )
        storyboards = await store.storyboards(job_id)
        approved = next((row for row in reversed(storyboards) if row.approved_at is not None), None)
        scenes = await store.scenes(approved.id) if approved is not None else []
        fallbacks = [scene.scene_key for scene in scenes if scene.is_fallback]
        return AdminJobDetail(
            job=job_view(job, fallbacks),
            events=[
                AdminEventView(
                    id=event.id,
                    type=event.type,
                    stage=event.stage,
                    payload=cast("dict[str, JsonValue]", dict(event.payload)),
                    created_at=event.created_at,
                )
                for event in await store.events(job_id)
            ],
            storyboard_versions=[
                AdminStoryboardVersion(
                    version=row.version,
                    origin=row.origin,
                    approved=row.approved_at is not None,
                    created_at=row.created_at,
                )
                for row in storyboards
            ],
            approved_storyboard=Storyboard.model_validate(approved.content) if approved is not None else None,
            scenes=[scene_view(scene) for scene in scenes],
            reports=public_reports(job.reports),
            cost=cost_view(await store.usage(job_id), job.credits_charged),
            trace_url=self._trace_url(job_id),
        )

    async def analytics(self, session: AsyncSession, query: AnalyticsQuery) -> JobAnalyticsView:
        start, end = resolve_range(query.date_from, query.date_to, self._clock.now().date())
        lower = datetime.combine(start, time.min, UTC)
        upper = datetime.combine(end, time.min, UTC) + timedelta(days=1)
        store = self._store_factory(session)
        days = zero_filled_days(start, end, await store.outcomes(lower, upper))
        scenes = await store.scene_totals(lower, upper)
        costs = await store.cost_totals(lower, upper)
        return JobAnalyticsView(
            date_from=start,
            date_to=end,
            days=days,
            success_rate=overall_success_rate(days),
            stages=stage_views(await store.stage_averages(lower, upper)),
            scenes=scenes.scenes,
            repair_rate=repair_rate(scenes),
            fallback_rate=fallback_rate(scenes),
            average_cost_micros_usd=costs.average_cost_micros_usd,
            average_credits_charged=costs.average_credits_charged,
        )

    def _trace_url(self, job_id: UUID) -> str | None:
        if not self._tracing.enabled:
            return None
        return trace_link(self._tracing.host, self._tracing.project_id, job_trace_id(job_id))
