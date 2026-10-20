import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from uuid import UUID

from motionile.modules.media.domain import is_terminal
from motionile.modules.media.ports import Transaction
from motionile.modules.media.render_events import RenderEvents, RenderProgress
from motionile.modules.media.schemas import RenderView
from motionile.modules.media.service import MediaService

HEARTBEAT_SECONDS = 15.0
POLL_SECONDS = 1.0
RECHECK_SECONDS = 10.0
HEARTBEAT_FRAME = b": heartbeat\n\n"

type Disconnected = Callable[[], Awaitable[bool]]


def sse_frame(event: str, data: str) -> bytes:
    return f"event: {event}\ndata: {data}\n\n".encode()


def snapshot_message(view: RenderView) -> RenderProgress:
    return RenderProgress(
        render_id=view.id,
        status=view.status,
        stage=view.stage,
        progress=view.progress,
        at=view.updated_at,
        error_code=view.error_code,
        error_message=view.error_message,
    )


async def current_state(
    transaction: Transaction, service: MediaService, user_id: UUID, render_id: UUID
) -> RenderProgress:
    async with transaction() as session:
        return snapshot_message(await service.get_render(session, user_id, render_id))


async def stream_render_events(  # noqa: PLR0913
    transaction: Transaction,
    service: MediaService,
    events: RenderEvents,
    user_id: UUID,
    render_id: UUID,
    *,
    is_disconnected: Disconnected,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
    poll_seconds: float = POLL_SECONDS,
    recheck_seconds: float = RECHECK_SECONDS,
) -> AsyncGenerator[bytes]:
    async with events.subscribe(render_id) as subscription:
        snapshot = await current_state(transaction, service, user_id, render_id)
        yield sse_frame("snapshot", snapshot.to_json())
        if snapshot.is_terminal:
            return
        loop = asyncio.get_running_loop()
        last_sent = last_checked = loop.time()
        while not await is_disconnected():
            message = await subscription.next(poll_seconds)
            now = loop.time()
            if message is not None:
                yield sse_frame("progress", message.to_json())
                last_sent = last_checked = now
                if message.is_terminal:
                    return
                continue
            if now - last_checked >= recheck_seconds:
                last_checked = now
                state = await current_state(transaction, service, user_id, render_id)
                if is_terminal(state.status):
                    yield sse_frame("progress", state.to_json())
                    return
            if now - last_sent >= heartbeat_seconds:
                last_sent = now
                yield HEARTBEAT_FRAME
