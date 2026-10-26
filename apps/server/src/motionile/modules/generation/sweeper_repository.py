from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.engine.ai.job_options import JobStatus
from motionile.modules.generation.domain import TERMINAL_JOB_STATUSES
from motionile.modules.generation.models import Job, Storyboard
from motionile.modules.generation.repository import FRESH_ROWS

TERMINAL_VALUES = tuple(status.value for status in TERMINAL_JOB_STATUSES)
STALL_EXEMPT_VALUES = (*TERMINAL_VALUES, JobStatus.AWAITING_APPROVAL.value)


@dataclass(frozen=True, slots=True)
class SweptJob:
    id: UUID
    user_id: UUID
    render_id: UUID | None


class SweepStore(Protocol):
    async def stalled(self, before: datetime, after: UUID | None, limit: int) -> list[SweptJob]: ...

    async def expired_approvals(self, before: datetime, after: UUID | None, limit: int) -> list[SweptJob]: ...

    async def cancelling(self, before: datetime, after: UUID | None, limit: int) -> list[SweptJob]: ...

    async def locked(self, job_id: UUID) -> Job | None: ...

    async def is_approved(self, job_id: UUID) -> bool: ...


class SqlSweepRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _page(self, conditions: list[ColumnElement[bool]], after: UUID | None, limit: int) -> list[SweptJob]:
        statement = select(Job.id, Job.user_id, Job.render_id).where(*conditions).order_by(Job.id).limit(limit)
        if after is not None:
            statement = statement.where(Job.id > after)
        return [SweptJob(*row) for row in (await self.session.execute(statement)).all()]

    async def stalled(self, before: datetime, after: UUID | None, limit: int) -> list[SweptJob]:
        return await self._page(
            [Job.status.not_in(STALL_EXEMPT_VALUES), Job.cancel_requested_at.is_(None), Job.updated_at < before],
            after,
            limit,
        )

    async def expired_approvals(self, before: datetime, after: UUID | None, limit: int) -> list[SweptJob]:
        return await self._page(
            [Job.status == JobStatus.AWAITING_APPROVAL.value, Job.updated_at < before], after, limit
        )

    async def cancelling(self, before: datetime, after: UUID | None, limit: int) -> list[SweptJob]:
        return await self._page(
            [Job.status.not_in(TERMINAL_VALUES), Job.cancel_requested_at.is_not(None), Job.updated_at < before],
            after,
            limit,
        )

    async def locked(self, job_id: UUID) -> Job | None:
        statement = select(Job).where(Job.id == job_id).with_for_update().execution_options(**FRESH_ROWS)
        return await self.session.scalar(statement)

    async def is_approved(self, job_id: UUID) -> bool:
        statement = (
            select(Storyboard.approved_at)
            .where(Storyboard.job_id == job_id)
            .order_by(Storyboard.version.desc())
            .limit(1)
        )
        return await self.session.scalar(statement) is not None
