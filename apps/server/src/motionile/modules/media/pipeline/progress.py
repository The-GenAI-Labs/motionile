import asyncio
import contextlib
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import Clock
from motionile.engine.render.models import CaptureCancelledError
from motionile.modules.media.domain import (
    RENDER_PIPELINE,
    STAGE_PROGRESS_WEIGHTS,
    RenderStage,
    RenderStatus,
)
from motionile.modules.media.ports import Transaction
from motionile.modules.media.render_events import RenderEvents, RenderProgress
from motionile.modules.media.render_repository import RenderJobStore

HEARTBEAT_SECONDS = 30.0
CANCEL_POLL_SECONDS = 5.0
MAX_RUNNING_PROGRESS = 99

type StoreFactory = Callable[[AsyncSession], RenderJobStore]

logger = structlog.get_logger(__name__)


def stage_base_progress(stage: RenderStage) -> int:
    return sum(STAGE_PROGRESS_WEIGHTS[earlier] for earlier in RENDER_PIPELINE[: RENDER_PIPELINE.index(stage)])


def stage_progress(stage: RenderStage, fraction: float) -> int:
    bounded = min(1.0, max(0.0, fraction))
    return min(MAX_RUNNING_PROGRESS, stage_base_progress(stage) + round(STAGE_PROGRESS_WEIGHTS[stage] * bounded))


class ProgressReporter:
    def __init__(
        self, transaction: Transaction, store_factory: StoreFactory, events: RenderEvents, clock: Clock, render_id: UUID
    ) -> None:
        self._transaction = transaction
        self._store_factory = store_factory
        self._events = events
        self._clock = clock
        self._render_id = render_id
        self._lock = asyncio.Lock()
        self._last = -1

    async def update(self, stage: RenderStage, fraction: float) -> None:
        value = stage_progress(stage, fraction)
        async with self._lock:
            if value <= self._last:
                return
            async with self._transaction() as session:
                touched = await self._store_factory(session).touch(self._render_id, progress=value, stage=stage)
            if touched:
                self._last = value
                await self.publish(stage.status, stage, value)

    async def publish(
        self,
        status: RenderStatus,
        stage: RenderStage | None,
        progress: int,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        await self._events.publish(
            RenderProgress(
                render_id=self._render_id,
                status=status,
                stage=stage,
                progress=progress,
                at=self._clock.now(),
                error_code=error_code,
                error_message=error_message,
            )
        )

    def remember(self, progress: int) -> None:
        self._last = max(self._last, progress)

    async def beat(self) -> None:
        async with self._transaction() as session:
            await self._store_factory(session).touch(self._render_id)

    @asynccontextmanager
    async def heartbeat(self, interval_seconds: float = HEARTBEAT_SECONDS) -> AsyncGenerator[None]:
        async def pulse() -> None:
            while True:
                await asyncio.sleep(interval_seconds)
                try:
                    await self.beat()
                except Exception:
                    logger.warning("media.render_heartbeat_failed", render_id=str(self._render_id))

        task = asyncio.ensure_future(pulse())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


class CancelWatch:
    def __init__(
        self,
        transaction: Transaction,
        store_factory: StoreFactory,
        events: RenderEvents,
        render_id: UUID,
        *,
        poll_seconds: float = CANCEL_POLL_SECONDS,
    ) -> None:
        self._transaction = transaction
        self._store_factory = store_factory
        self._events = events
        self._render_id = render_id
        self._poll_seconds = poll_seconds
        self._requested = False
        self._checked_at = 0.0

    async def requested(self) -> bool:
        if self._requested:
            return True
        if await self._events.cancel_flagged(self._render_id):
            self._requested = True
            return True
        loop_time = asyncio.get_running_loop().time()
        if loop_time - self._checked_at >= self._poll_seconds:
            self._checked_at = loop_time
            async with self._transaction() as session:
                render = await self._store_factory(session).get_unscoped(self._render_id)
            self._requested = render is not None and render.cancel_requested_at is not None
        return self._requested

    async def raise_if_requested(self) -> None:
        if await self.requested():
            raise CaptureCancelledError("The render was cancelled")
