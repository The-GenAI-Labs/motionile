from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import ColumnElement, Date, Float, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.pagination import Cursor, keyset_page
from motionile.engine.ai.job_options import JobStatus
from motionile.modules.credits import UsageRecord
from motionile.modules.generation.analytics import OutcomeCounts, SceneTotals, StageAverage
from motionile.modules.generation.models import Job, JobEvent, Scene, Storyboard
from motionile.modules.generation.repository import FRESH_ROWS

EVENT_LIMIT = 500
STAGE_EVENT = "stage.completed"
OUTCOME_STATUSES = (JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value)


@dataclass(frozen=True, slots=True)
class AdminJobFilter:
    status: JobStatus | None = None
    source: str | None = None
    user_id: UUID | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None


@dataclass(frozen=True, slots=True)
class UsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    audio_characters: int = 0
    render_ms: int = 0
    cost_micros_usd: int = 0
    records: int = 0


@dataclass(frozen=True, slots=True)
class CostTotals:
    average_cost_micros_usd: float | None
    average_credits_charged: float | None


class AdminStore(Protocol):
    async def page(self, job_filter: AdminJobFilter, cursor: Cursor | None, limit: int) -> list[Job]: ...

    async def job(self, job_id: UUID) -> Job | None: ...

    async def events(self, job_id: UUID) -> list[JobEvent]: ...

    async def storyboards(self, job_id: UUID) -> list[Storyboard]: ...

    async def scenes(self, storyboard_id: UUID) -> list[Scene]: ...

    async def usage(self, job_id: UUID) -> UsageTotals: ...

    async def outcomes(self, start: datetime, end: datetime) -> OutcomeCounts: ...

    async def stage_averages(self, start: datetime, end: datetime) -> list[StageAverage]: ...

    async def scene_totals(self, start: datetime, end: datetime) -> SceneTotals: ...

    async def cost_totals(self, start: datetime, end: datetime) -> CostTotals: ...


def completed_between(start: datetime, end: datetime) -> list[ColumnElement[bool]]:
    return [Job.status == JobStatus.COMPLETED.value, Job.completed_at >= start, Job.completed_at < end]


class SqlAdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def page(self, job_filter: AdminJobFilter, cursor: Cursor | None, limit: int) -> list[Job]:
        statement = select(Job)
        if job_filter.status is not None:
            statement = statement.where(Job.status == job_filter.status.value)
        if job_filter.source is not None:
            statement = statement.where(Job.source == job_filter.source)
        if job_filter.user_id is not None:
            statement = statement.where(Job.user_id == job_filter.user_id)
        if job_filter.created_from is not None:
            statement = statement.where(Job.created_at >= job_filter.created_from)
        if job_filter.created_to is not None:
            statement = statement.where(Job.created_at < job_filter.created_to)
        paged = keyset_page(statement, created_at=Job.created_at, id_=Job.id, cursor=cursor, limit=limit)
        return list(await self.session.scalars(paged.execution_options(**FRESH_ROWS)))

    async def job(self, job_id: UUID) -> Job | None:
        statement = select(Job).where(Job.id == job_id).execution_options(**FRESH_ROWS)
        return await self.session.scalar(statement)

    async def events(self, job_id: UUID) -> list[JobEvent]:
        statement = (
            select(JobEvent)
            .where(JobEvent.job_id == job_id)
            .order_by(JobEvent.id)
            .limit(EVENT_LIMIT)
            .execution_options(**FRESH_ROWS)
        )
        return list(await self.session.scalars(statement))

    async def storyboards(self, job_id: UUID) -> list[Storyboard]:
        statement = (
            select(Storyboard)
            .where(Storyboard.job_id == job_id)
            .order_by(Storyboard.version)
            .execution_options(**FRESH_ROWS)
        )
        return list(await self.session.scalars(statement))

    async def scenes(self, storyboard_id: UUID) -> list[Scene]:
        statement = (
            select(Scene)
            .where(Scene.storyboard_id == storyboard_id)
            .order_by(Scene.position)
            .execution_options(**FRESH_ROWS)
        )
        return list(await self.session.scalars(statement))

    async def usage(self, job_id: UUID) -> UsageTotals:
        statement = select(
            func.coalesce(func.sum(UsageRecord.input_tokens), 0),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0),
            func.coalesce(func.sum(UsageRecord.audio_characters), 0),
            func.coalesce(func.sum(UsageRecord.render_ms), 0),
            func.coalesce(func.sum(UsageRecord.cost_micros_usd), 0),
            func.count(UsageRecord.id),
        ).where(UsageRecord.job_id == job_id)
        row = (await self.session.execute(statement)).one()
        return UsageTotals(*(int(value) for value in row))

    async def outcomes(self, start: datetime, end: datetime) -> OutcomeCounts:
        day = cast(func.timezone("UTC", Job.completed_at), Date)
        statement = (
            select(day, Job.status, func.count())
            .where(Job.status.in_(OUTCOME_STATUSES), Job.completed_at >= start, Job.completed_at < end)
            .group_by(day, Job.status)
        )
        counts: dict[tuple[date, str], int] = {}
        for found_day, status, count in (await self.session.execute(statement)).all():
            counts[(found_day, status)] = int(count)
        return counts

    async def stage_averages(self, start: datetime, end: datetime) -> list[StageAverage]:
        stage = func.jsonb_extract_path_text(JobEvent.payload, "stage")
        duration: ColumnElement[float] = cast(func.jsonb_extract_path_text(JobEvent.payload, "durationMs"), Float)
        statement = (
            select(stage, func.avg(duration), func.count())
            .where(JobEvent.type == STAGE_EVENT, JobEvent.created_at >= start, JobEvent.created_at < end)
            .group_by(stage)
        )
        return [
            StageAverage(found, float(average), int(count))
            for found, average, count in (await self.session.execute(statement)).all()
            if found is not None and average is not None
        ]

    async def scene_totals(self, start: datetime, end: datetime) -> SceneTotals:
        statement = (
            select(
                func.count(Scene.id),
                func.count(Scene.id).filter(Scene.repair_attempts > 0),
                func.count(Scene.id).filter(Scene.is_fallback.is_(True)),
            )
            .join(Storyboard, Storyboard.id == Scene.storyboard_id)
            .join(Job, Job.id == Storyboard.job_id)
            .where(*completed_between(start, end))
        )
        scenes, repaired, fallbacks = (await self.session.execute(statement)).one()
        return SceneTotals(int(scenes), int(repaired), int(fallbacks))

    async def cost_totals(self, start: datetime, end: datetime) -> CostTotals:
        per_job = (
            select(func.sum(UsageRecord.cost_micros_usd).label("cost"))
            .join(Job, Job.id == UsageRecord.job_id)
            .where(*completed_between(start, end))
            .group_by(UsageRecord.job_id)
            .subquery()
        )
        average_cost = await self.session.scalar(select(func.avg(per_job.c.cost)))
        average_credits = await self.session.scalar(
            select(func.avg(Job.credits_charged)).where(*completed_between(start, end))
        )
        return CostTotals(
            float(average_cost) if average_cost is not None else None,
            float(average_credits) if average_credits is not None else None,
        )
