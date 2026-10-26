import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Final, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.modules.generation.exceptions import JobNotFoundError
from motionile.modules.generation.job_events import JobMessage, JobSubscription
from motionile.modules.generation.models import JobEvent
from motionile.modules.generation.repository import SqlJobRepository
from motionile.modules.generation.schemas import JobView
from motionile.modules.generation.service import GenerationService

HEARTBEAT_SECONDS: Final = 15.0
POLL_SECONDS: Final = 1.0
RECHECK_SECONDS: Final = 10.0
RENEW_SECONDS: Final = 10.0
REPLAY_PAGE: Final = 200
SEEN_LIMIT: Final = 5_000
HEARTBEAT_FRAME: Final = b": heartbeat\n\n"
SNAPSHOT_EVENT: Final = "snapshot"
MESSAGE_EVENT: Final = "job_event"

type Disconnected = Callable[[], Awaitable[bool]]
type Transaction = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class StreamSource(Protocol):
    async def snapshot(self) -> JobView: ...

    async def events_after(self, after: UUID | None, limit: int) -> list[JobMessage]: ...


class Subscribable(Protocol):
    def subscribe(self, job_id: UUID) -> AbstractAsyncContextManager[JobSubscription]: ...


class Lease(Protocol):
    async def renew(self) -> None: ...

    async def release(self) -> None: ...


def parse_last_event_id(raw: str | None) -> UUID | None:
    if raw is None:
        return None
    try:
        return UUID(raw.strip())
    except ValueError:
        return None


def snapshot_frame(view: JobView) -> bytes:
    return f"event: {SNAPSHOT_EVENT}\ndata: {view.model_dump_json(by_alias=True)}\n\n".encode()


def message_frame(message: JobMessage) -> bytes:
    identifier = f"id: {message.id}\n" if message.id is not None else ""
    return f"{identifier}event: {MESSAGE_EVENT}\ndata: {message.to_json()}\n\n".encode()


def message_of(event: JobEvent) -> JobMessage:
    return JobMessage(id=event.id, type=event.type, stage=event.stage, payload=dict(event.payload), at=event.created_at)


class JobStreamSource:
    def __init__(self, transaction: Transaction, service: GenerationService, user_id: UUID, job_id: UUID) -> None:
        self._transaction = transaction
        self._service = service
        self._user_id = user_id
        self._job_id = job_id

    async def snapshot(self) -> JobView:
        async with self._transaction() as session:
            return await self._service.get(session, self._user_id, self._job_id)

    async def events_after(self, after: UUID | None, limit: int) -> list[JobMessage]:
        async with self._transaction() as session:
            rows = await SqlJobRepository(session).events_after(self._user_id, self._job_id, after, limit)
        return [message_of(row) for row in rows]


class Delivery:
    def __init__(self, after: UUID | None) -> None:
        self.last_id = after
        self._seen: dict[UUID, None] = {}

    def fresh(self, message: JobMessage) -> bool:
        if message.id is None:
            return True
        if message.id in self._seen:
            return False
        self._seen[message.id] = None
        if len(self._seen) > SEEN_LIMIT:
            del self._seen[next(iter(self._seen))]
        if self.last_id is None or message.id.int > self.last_id.int:
            self.last_id = message.id
        return True


async def pending_events(source: StreamSource, delivery: Delivery) -> AsyncGenerator[JobMessage]:
    while True:
        batch = await source.events_after(delivery.last_id, REPLAY_PAGE)
        for message in batch:
            if delivery.fresh(message):
                yield message
        if len(batch) < REPLAY_PAGE:
            return


@dataclass(slots=True)
class Step:
    frames: list[bytes] = field(default_factory=list[bytes])
    ended: bool = False


@dataclass(frozen=True, slots=True)
class Timing:
    heartbeat_seconds: float = HEARTBEAT_SECONDS
    recheck_seconds: float = RECHECK_SECONDS
    renew_seconds: float = RENEW_SECONDS


class Follower:
    def __init__(
        self, source: StreamSource, delivery: Delivery, lease: Lease | None, timing: Timing, started: float
    ) -> None:
        self._source = source
        self._delivery = delivery
        self._lease = lease
        self._timing = timing
        self._last_sent = self._last_checked = self._last_renewed = started

    async def maintain(self, now: float) -> None:
        if self._lease is not None and now - self._last_renewed >= self._timing.renew_seconds:
            self._last_renewed = now
            await self._lease.renew()

    async def on_message(self, message: JobMessage, now: float) -> Step:
        if not self._delivery.fresh(message):
            return Step()
        self._last_sent = now
        return Step([message_frame(message)], message.is_terminal)

    async def on_idle(self, now: float) -> Step:
        step = Step()
        if now - self._last_checked >= self._timing.recheck_seconds:
            self._last_checked = now
            step = await self._resync(now)
        if not step.ended and not step.frames and now - self._last_sent >= self._timing.heartbeat_seconds:
            self._last_sent = now
            step.frames.append(HEARTBEAT_FRAME)
        return step

    async def _resync(self, now: float) -> Step:
        try:
            current = await self._source.snapshot()
        except JobNotFoundError:
            return Step(ended=True)
        step = Step()
        async for missed in pending_events(self._source, self._delivery):
            step.frames.append(message_frame(missed))
            self._last_sent = now
            if missed.is_terminal:
                step.ended = True
                return step
        step.ended = current.status.is_terminal
        return step


async def stream_job_events(  # noqa: PLR0913
    source: StreamSource,
    events: Subscribable,
    job_id: UUID,
    *,
    after: UUID | None,
    is_disconnected: Disconnected,
    lease: Lease | None = None,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
    poll_seconds: float = POLL_SECONDS,
    recheck_seconds: float = RECHECK_SECONDS,
) -> AsyncGenerator[bytes]:
    try:
        async with events.subscribe(job_id) as subscription:
            try:
                current = await source.snapshot()
            except JobNotFoundError:
                return
            yield snapshot_frame(current)
            delivery = Delivery(after)
            async for message in pending_events(source, delivery):
                yield message_frame(message)
                if message.is_terminal:
                    return
            if current.status.is_terminal:
                return
            loop = asyncio.get_running_loop()
            follower = Follower(
                source, delivery, lease, Timing(heartbeat_seconds, recheck_seconds, RENEW_SECONDS), loop.time()
            )
            while not await is_disconnected():
                message = await subscription.next(poll_seconds)
                now = loop.time()
                await follower.maintain(now)
                step = await follower.on_message(message, now) if message else await follower.on_idle(now)
                for frame in step.frames:
                    yield frame
                if step.ended:
                    return
    finally:
        if lease is not None:
            await lease.release()
