from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import timedelta
from typing import Final, Protocol
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import Clock
from motionile.engine.ai.job_options import JobStatus
from motionile.modules.generation.runtime_settings import RuntimeSettings
from motionile.modules.generation.service import GenerationService
from motionile.modules.generation.sweeper_repository import SqlSweepRepository, SweepStore, SweptJob
from motionile.modules.media import RenderNotFoundError

type Transaction = Callable[[], AbstractAsyncContextManager[AsyncSession]]
type SweepStoreFactory = Callable[[AsyncSession], SweepStore]
type Selector = Callable[[SweepStore, UUID | None], Awaitable[list[SweptJob]]]
type Handler = Callable[[AsyncSession, SweepStore, SweptJob], Awaitable[bool]]

PAGE_SIZE: Final = 50
MAX_PAGES: Final = 4
CANCEL_GRACE: Final = timedelta(minutes=2)
STALLED_CODE: Final = "job_stalled"
STALLED_MESSAGE: Final = "The job stopped making progress."
APPROVAL_EXPIRED: Final = "approval_expired"

logger = structlog.get_logger(__name__)


class RenderCanceller(Protocol):
    async def cancel_render(self, session: AsyncSession, user_id: UUID, render_id: UUID) -> object: ...


class Sweeper:
    def __init__(  # noqa: PLR0913, PLR0917
        self,
        transaction: Transaction,
        service: GenerationService,
        settings: RuntimeSettings,
        clock: Clock,
        renders: RenderCanceller,
        store_factory: SweepStoreFactory = SqlSweepRepository,
    ) -> None:
        self._transaction = transaction
        self._service = service
        self._settings = settings
        self._clock = clock
        self._renders = renders
        self._store_factory = store_factory

    async def fail_stalled_jobs(self) -> int:
        async with self._transaction() as session:
            timeout = await self._settings.stage_timeout(session)
        before = self._clock.now() - timeout
        stalled = await self._sweep(lambda store, after: store.stalled(before, after, PAGE_SIZE), self._fail)
        unresumed = await self._sweep(
            lambda store, after: store.unresumed_approvals(before, after, PAGE_SIZE), self._fail_unresumed
        )
        return stalled + unresumed

    async def cancel_expired_approvals(self) -> int:
        async with self._transaction() as session:
            timeout = await self._settings.approval_timeout(session)
        before = self._clock.now() - timeout
        return await self._sweep(lambda store, after: store.expired_approvals(before, after, PAGE_SIZE), self._expire)

    async def finalize_cancelled_jobs(self) -> int:
        before = self._clock.now() - CANCEL_GRACE
        return await self._sweep(lambda store, after: store.cancelling(before, after, PAGE_SIZE), self._finalize)

    async def _sweep(self, select: Selector, handle: Handler) -> int:
        handled = 0
        after: UUID | None = None
        for _ in range(MAX_PAGES):
            async with self._transaction() as session:
                page = await select(self._store_factory(session), after)
            for job in page:
                handled += await self._one(job, handle)
            if len(page) < PAGE_SIZE:
                break
            after = page[-1].id
        return handled

    async def _one(self, job: SweptJob, handle: Handler) -> int:
        try:
            async with self._transaction() as session:
                return int(await handle(session, self._store_factory(session), job))
        except Exception:
            logger.exception("generation.sweep_failed", job_id=str(job.id))
            return 0

    async def _cancel_render(self, session: AsyncSession, job: SweptJob) -> None:
        if job.render_id is None:
            return
        try:
            await self._renders.cancel_render(session, job.user_id, job.render_id)
        except RenderNotFoundError:
            logger.info("generation.sweep_render_missing", job_id=str(job.id))

    async def _fail(self, session: AsyncSession, store: SweepStore, job: SweptJob) -> bool:
        del store
        await self._cancel_render(session, job)
        return await self._service.fail_job(session, job.id, STALLED_CODE, STALLED_MESSAGE)

    async def _fail_unresumed(self, session: AsyncSession, store: SweepStore, job: SweptJob) -> bool:
        current = await store.locked(job.id)
        if (
            current is None
            or current.status != JobStatus.AWAITING_APPROVAL.value
            or current.cancel_requested_at is not None
            or not await store.is_approved(job.id)
        ):
            return False
        return await self._service.fail_job(session, job.id, STALLED_CODE, STALLED_MESSAGE)

    async def _expire(self, session: AsyncSession, store: SweepStore, job: SweptJob) -> bool:
        current = await store.locked(job.id)
        if current is None or current.status != JobStatus.AWAITING_APPROVAL.value or await store.is_approved(job.id):
            return False
        return await self._service.finish_cancellation(session, job.id, APPROVAL_EXPIRED)

    async def _finalize(self, session: AsyncSession, store: SweepStore, job: SweptJob) -> bool:
        current = await store.locked(job.id)
        if current is None or current.cancel_requested_at is None:
            return False
        await self._cancel_render(session, job)
        return await self._service.finish_cancellation(session, job.id)
