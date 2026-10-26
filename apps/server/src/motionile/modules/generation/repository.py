from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.ids import new_id
from motionile.core.pagination import Cursor, keyset_page
from motionile.engine.ai.job_options import JobStatus
from motionile.modules.generation.domain import ACTIVE_JOB_STATUSES, JOB_TRANSITIONS, TERMINAL_JOB_STATUSES
from motionile.modules.generation.models import Job, JobEvent, Scene, Storyboard

FRESH_ROWS = {"populate_existing": True}
ACTIVE_VALUES = tuple(status.value for status in ACTIVE_JOB_STATUSES)
TERMINAL_VALUES = tuple(status.value for status in TERMINAL_JOB_STATUSES)
CREATE_LOCK_NAMESPACE = "jobs.create"
STORYBOARD_VERSION_CONSTRAINT = "uq_storyboards_job_id_version"


def sources_for(target: JobStatus) -> frozenset[JobStatus]:
    return frozenset(status for status, targets in JOB_TRANSITIONS.items() if target in targets)


def violates(error: IntegrityError, name: str) -> bool:
    return name in str(error.orig)


@dataclass(frozen=True, slots=True)
class NewJob:
    id: UUID
    user_id: UUID
    source: str
    topic_id: UUID | None
    parent_job_id: UUID | None
    query: str
    options: Mapping[str, Any]
    credits_estimated: int
    credits_reserved: int
    idempotency_key: str | None


@dataclass(frozen=True, slots=True)
class NewStoryboard:
    job_id: UUID
    version: int
    origin: str
    content: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class NewJobEvent:
    job_id: UUID
    type: str
    stage: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class JobFilter:
    status: JobStatus | None = None
    source: str | None = None
    topic_id: UUID | None = None


class JobStore(Protocol):
    async def lock_creation(self, user_id: UUID) -> None: ...

    async def count_active(self, user_id: UUID) -> int: ...

    async def insert(self, row: NewJob) -> Job: ...

    async def get_owned(self, user_id: UUID, job_id: UUID, *, lock: bool = False) -> Job | None: ...

    async def get_for_pipeline(self, job_id: UUID, *, lock: bool = False) -> Job | None: ...

    async def get_by_key(self, user_id: UUID, idempotency_key: str) -> Job | None: ...

    async def page(self, user_id: UUID, job_filter: JobFilter, cursor: Cursor | None, limit: int) -> list[Job]: ...

    async def transition(
        self, job_id: UUID, target: JobStatus, sources: Collection[JobStatus], values: Mapping[str, Any]
    ) -> Job | None: ...

    async def request_cancel(self, job_id: UUID, at: datetime) -> Job | None: ...

    async def delete(self, user_id: UUID, job_id: UUID) -> bool: ...

    async def fallback_scene_keys(self, job_ids: Collection[UUID]) -> dict[UUID, list[str]]: ...

    async def latest_storyboard(self, user_id: UUID, job_id: UUID) -> Storyboard | None: ...

    async def storyboard_pipeline(self, job_id: UUID) -> Storyboard | None: ...

    async def insert_storyboard(self, row: NewStoryboard) -> Storyboard | None: ...

    async def approve_storyboard(self, storyboard_id: UUID, approver_id: UUID, at: datetime) -> bool: ...

    async def scenes(self, user_id: UUID, job_id: UUID) -> list[Scene]: ...

    async def add_event(self, row: NewJobEvent) -> JobEvent: ...

    async def events_after(self, user_id: UUID, job_id: UUID, after: UUID | None, limit: int) -> list[JobEvent]: ...

    async def events_for_admin(self, job_id: UUID, limit: int) -> list[JobEvent]: ...


class SqlJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lock_creation(self, user_id: UUID) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:name, 0))"),
            {"name": f"{CREATE_LOCK_NAMESPACE}:{user_id}"},
        )

    async def count_active(self, user_id: UUID) -> int:
        statement = select(func.count()).select_from(Job).where(Job.user_id == user_id, Job.status.in_(ACTIVE_VALUES))
        return int(await self.session.scalar(statement) or 0)

    async def insert(self, row: NewJob) -> Job:
        job = Job(
            id=row.id,
            user_id=row.user_id,
            source=row.source,
            topic_id=row.topic_id,
            parent_job_id=row.parent_job_id,
            query=row.query,
            options=dict(row.options),
            status=JobStatus.QUEUED.value,
            credits_estimated=row.credits_estimated,
            credits_reserved=row.credits_reserved,
            idempotency_key=row.idempotency_key,
            reports={},
        )
        self.session.add(job)
        await self.session.flush()
        await self.session.refresh(job)
        return job

    async def get_owned(self, user_id: UUID, job_id: UUID, *, lock: bool = False) -> Job | None:
        statement = select(Job).where(Job.id == job_id, Job.user_id == user_id).execution_options(**FRESH_ROWS)
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_for_pipeline(self, job_id: UUID, *, lock: bool = False) -> Job | None:
        statement = select(Job).where(Job.id == job_id).execution_options(**FRESH_ROWS)
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_by_key(self, user_id: UUID, idempotency_key: str) -> Job | None:
        statement = (
            select(Job)
            .where(Job.user_id == user_id, Job.idempotency_key == idempotency_key)
            .execution_options(**FRESH_ROWS)
        )
        return await self.session.scalar(statement)

    async def page(self, user_id: UUID, job_filter: JobFilter, cursor: Cursor | None, limit: int) -> list[Job]:
        statement = select(Job).where(Job.user_id == user_id)
        if job_filter.status is not None:
            statement = statement.where(Job.status == job_filter.status.value)
        if job_filter.source is not None:
            statement = statement.where(Job.source == job_filter.source)
        if job_filter.topic_id is not None:
            statement = statement.where(Job.topic_id == job_filter.topic_id)
        paged = keyset_page(
            statement, created_at=Job.created_at, id_=Job.id, cursor=cursor, limit=limit
        ).execution_options(**FRESH_ROWS)
        return list(await self.session.scalars(paged))

    async def transition(
        self, job_id: UUID, target: JobStatus, sources: Collection[JobStatus], values: Mapping[str, Any]
    ) -> Job | None:
        statement = (
            update(Job)
            .where(Job.id == job_id, Job.status.in_([source.value for source in sources]))
            .values(status=target.value, updated_at=func.now(), **values)
            .returning(Job)
            .execution_options(**FRESH_ROWS)
        )
        return await self.session.scalar(statement)

    async def request_cancel(self, job_id: UUID, at: datetime) -> Job | None:
        statement = (
            update(Job)
            .where(Job.id == job_id, Job.status.not_in(TERMINAL_VALUES))
            .values(cancel_requested_at=func.coalesce(Job.cancel_requested_at, at), updated_at=func.now())
            .returning(Job)
            .execution_options(**FRESH_ROWS)
        )
        return await self.session.scalar(statement)

    async def delete(self, user_id: UUID, job_id: UUID) -> bool:
        statement = delete(Job).where(Job.id == job_id, Job.user_id == user_id).returning(Job.id)
        return await self.session.scalar(statement) is not None

    async def fallback_scene_keys(self, job_ids: Collection[UUID]) -> dict[UUID, list[str]]:
        if not job_ids:
            return {}
        statement = (
            select(Storyboard.job_id, Scene.scene_key)
            .join(Scene, Scene.storyboard_id == Storyboard.id)
            .where(Storyboard.job_id.in_(job_ids), Scene.is_fallback.is_(True))
            .order_by(Storyboard.job_id, Scene.position)
        )
        keys: dict[UUID, list[str]] = {}
        for job_id, scene_key in (await self.session.execute(statement)).all():
            keys.setdefault(job_id, []).append(scene_key)
        return keys

    async def latest_storyboard(self, user_id: UUID, job_id: UUID) -> Storyboard | None:
        statement = (
            select(Storyboard)
            .join(Job, Job.id == Storyboard.job_id)
            .where(Storyboard.job_id == job_id, Job.user_id == user_id)
            .order_by(Storyboard.version.desc())
            .limit(1)
            .execution_options(**FRESH_ROWS)
        )
        return await self.session.scalar(statement)

    async def storyboard_pipeline(self, job_id: UUID) -> Storyboard | None:
        statement = (
            select(Storyboard)
            .where(Storyboard.job_id == job_id)
            .order_by(Storyboard.version.desc())
            .limit(1)
            .execution_options(**FRESH_ROWS)
        )
        return await self.session.scalar(statement)

    async def insert_storyboard(self, row: NewStoryboard) -> Storyboard | None:
        storyboard = Storyboard(
            id=new_id(), job_id=row.job_id, version=row.version, origin=row.origin, content=dict(row.content)
        )
        try:
            async with self.session.begin_nested():
                self.session.add(storyboard)
                await self.session.flush()
        except IntegrityError as error:
            if violates(error, STORYBOARD_VERSION_CONSTRAINT):
                return None
            raise
        await self.session.refresh(storyboard)
        return storyboard

    async def approve_storyboard(self, storyboard_id: UUID, approver_id: UUID, at: datetime) -> bool:
        statement = (
            update(Storyboard)
            .where(Storyboard.id == storyboard_id, Storyboard.approved_at.is_(None))
            .values(approved_at=at, approved_by=approver_id, updated_at=func.now())
            .returning(Storyboard.id)
        )
        return await self.session.scalar(statement) is not None

    async def scenes(self, user_id: UUID, job_id: UUID) -> list[Scene]:
        statement = (
            select(Scene)
            .join(Storyboard, Storyboard.id == Scene.storyboard_id)
            .join(Job, Job.id == Storyboard.job_id)
            .where(Storyboard.job_id == job_id, Job.user_id == user_id)
            .order_by(Storyboard.version.desc(), Scene.position)
            .execution_options(**FRESH_ROWS)
        )
        return list(await self.session.scalars(statement))

    async def add_event(self, row: NewJobEvent) -> JobEvent:
        event = JobEvent(id=new_id(), job_id=row.job_id, type=row.type, stage=row.stage, payload=dict(row.payload))
        self.session.add(event)
        await self.session.flush()
        return event

    async def events_after(self, user_id: UUID, job_id: UUID, after: UUID | None, limit: int) -> list[JobEvent]:
        statement = (
            select(JobEvent)
            .join(Job, Job.id == JobEvent.job_id)
            .where(JobEvent.job_id == job_id, Job.user_id == user_id)
            .order_by(JobEvent.id)
            .limit(limit)
            .execution_options(**FRESH_ROWS)
        )
        if after is not None:
            statement = statement.where(JobEvent.id > after)
        return list(await self.session.scalars(statement))

    async def events_for_admin(self, job_id: UUID, limit: int) -> list[JobEvent]:
        statement = (
            select(JobEvent)
            .where(JobEvent.job_id == job_id)
            .order_by(JobEvent.id)
            .limit(limit)
            .execution_options(**FRESH_ROWS)
        )
        return list(await self.session.scalars(statement))
