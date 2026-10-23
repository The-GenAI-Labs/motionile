from datetime import timedelta

import structlog

from motionile.core.clock import Clock
from motionile.modules.media.domain import RenderFailureCode, RenderStage, RenderStatus
from motionile.modules.media.models import Render
from motionile.modules.media.pipeline.context import JobStoreFactory
from motionile.modules.media.ports import Transaction
from motionile.modules.media.render_events import RenderEvents, RenderProgress
from motionile.modules.media.render_repository import Finish

STALLED_MESSAGE = "The render stopped making progress and was ended."
BATCH_SIZE = 100

logger = structlog.get_logger(__name__)


def terminal_message(render: Render) -> RenderProgress:
    return RenderProgress(
        render_id=render.id,
        status=RenderStatus(render.status),
        stage=RenderStage(render.stage) if render.stage is not None else None,
        progress=render.progress,
        at=render.updated_at,
        error_code=render.error_code,
        error_message=render.error_message,
    )


async def fail_stalled_renders(
    transaction: Transaction,
    store_factory: JobStoreFactory,
    events: RenderEvents,
    clock: Clock,
    stall_seconds: int,
) -> int:
    before = clock.now() - timedelta(seconds=stall_seconds)
    total = 0
    while True:
        failed: list[Render] = []
        async with transaction() as session:
            store = store_factory(session)
            candidates = await store.stalled(before, BATCH_SIZE)
            for render_id in candidates:
                row = await store.finish(
                    render_id,
                    Finish(
                        target=RenderStatus.FAILED,
                        at=clock.now(),
                        error_code=RenderFailureCode.RENDER_STALLED.value,
                        error_message=STALLED_MESSAGE,
                        stalled_before=before,
                    ),
                )
                if row is not None:
                    failed.append(row)
        for render in failed:
            await events.publish(terminal_message(render))
        total += len(failed)
        if len(candidates) < BATCH_SIZE or not failed:
            break
    if total:
        logger.warning("media.renders_stalled", count=total)
    return total
