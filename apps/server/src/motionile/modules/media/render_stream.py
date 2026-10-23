import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from motionile.modules.media.domain import is_terminal
from motionile.modules.media.ports import Transaction
from motionile.modules.media.render_events import RenderEvents, RenderProgress
from motionile.modules.media.schemas import RenderView
from motionile.modules.media.service import MediaService
from motionile.modules.media.stream_slots import StreamLease

HEARTBEAT_SECONDS = 15.0
POLL_SECONDS = 1.0
RECHECK_SECONDS = 10.0
HEARTBEAT_FRAME = b": heartbeat\n\n"

type Disconnected = Callable[[], Awaitable[bool]]
type Authorize = Callable[[], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class StreamGuards:
    authorize: Authorize
    lease: StreamLease


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
    guards: StreamGuards | None = None,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
    poll_seconds: float = POLL_SECONDS,
    recheck_seconds: float = RECHECK_SECONDS,
) -> AsyncGenerator[bytes]:
    try:
        async with events.subscribe(render_id) as subscription:
            if guards is not None and not await guards.authorize():
                return
            snapshot = await current_state(transaction, service, user_id, render_id)
            yield sse_frame("snapshot", snapshot.to_json())
            if snapshot.is_terminal:
                return
            loop = asyncio.get_running_loop()
            last_sent = last_checked = last_authorized = loop.time()
            while not await is_disconnected():
                message = await subscription.next(poll_seconds)
                now = loop.time()
                if guards is not None and now - last_authorized >= recheck_seconds:
                    last_authorized = now
                    if not await guards.authorize():
                        return
                    await guards.lease.renew()
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
    finally:
        if guards is not None:
            await guards.lease.release()
