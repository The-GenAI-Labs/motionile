import asyncio
import json
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import JsonValue
from tests.fakes.generation import GenerationWorld

from motionile.core.ids import new_id
from motionile.engine.ai.job_options import JobStatus
from motionile.modules.generation.exceptions import JobNotFoundError
from motionile.modules.generation.job_events import JobMessage, JobSubscription
from motionile.modules.generation.schemas import JobView
from motionile.modules.generation.stream import (
    HEARTBEAT_FRAME,
    MAX_STREAM_SECONDS,
    RECONNECT_FRAME,
    message_frame,
    parse_last_event_id,
    stream_job_events,
)
from motionile.modules.generation.views import job_view

AT = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


def event(event_type: str, payload: Mapping[str, JsonValue] | None = None) -> JobMessage:
    return JobMessage(id=new_id(), type=event_type, stage="plan", payload=dict(payload or {}), at=AT)


class FakePubSub:
    def __init__(self) -> None:
        self.queue: list[JobMessage] = []

    async def subscribe(self, channel: str) -> None:
        del channel

    async def unsubscribe(self, channel: str) -> None:
        del channel

    async def aclose(self) -> None:
        return None

    async def get_message(
        self,
        *,
        ignore_subscribe_messages: bool,
        timeout: float,  # noqa: ASYNC109
    ) -> Mapping[str, object] | None:
        del ignore_subscribe_messages
        if not self.queue:
            await asyncio.sleep(min(timeout, 0.001))
            return None
        return {"data": self.queue.pop(0).to_json()}


class FakeEvents:
    def __init__(self) -> None:
        self.pubsub = FakePubSub()
        self.subscribed: list[UUID] = []

    @asynccontextmanager
    async def subscribe(self, job_id: UUID) -> AsyncGenerator[JobSubscription]:
        self.subscribed.append(job_id)
        yield JobSubscription(self.pubsub)


class FakeSource:
    def __init__(self, view: JobView, events: FakeEvents | None = None) -> None:
        self.view = view
        self.events = events
        self.subscriptions_at_query: list[int] = []
        self.stored: list[JobMessage] = []
        self.missing = False
        self.snapshots = 0
        self.queries: list[UUID | None] = []

    async def snapshot(self) -> JobView:
        self.snapshots += 1
        if self.missing:
            raise JobNotFoundError
        return self.view

    async def events_after(self, after: UUID | None, limit: int) -> list[JobMessage]:
        self.queries.append(after)
        self.subscriptions_at_query.append(len(self.events.subscribed) if self.events is not None else 0)
        rows = [message for message in self.stored if after is None or (message.id and message.id.int > after.int)]
        return rows[:limit]

    def finish(self, status: JobStatus) -> None:
        self.view = self.view.model_copy(update={"status": status})


class FakeLease:
    def __init__(self) -> None:
        self.renewed = 0
        self.released = 0

    async def renew(self) -> None:
        self.renewed += 1

    async def release(self) -> None:
        self.released += 1


def view_with(status: str = "planning") -> JobView:
    world = GenerationWorld()
    return job_view(world.add_job(new_id(), status=status))


async def collect(  # noqa: PLR0913
    source: FakeSource,
    events: FakeEvents,
    *,
    after: UUID | None = None,
    polls: int = 3,
    lease: FakeLease | None = None,
    heartbeat: float = 15.0,
    recheck: float = 10.0,
) -> list[bytes]:
    remaining = polls

    async def disconnected() -> bool:
        nonlocal remaining
        remaining -= 1
        return remaining < 0

    stream = stream_job_events(
        source,
        events,
        new_id(),
        after=after,
        is_disconnected=disconnected,
        lease=lease,
        heartbeat_seconds=heartbeat,
        poll_seconds=0.001,
        recheck_seconds=recheck,
    )
    return [frame async for frame in stream]


def decode(frame: bytes) -> tuple[str | None, str, dict[str, object]]:
    lines = frame.decode().strip().split("\n")
    fields = dict(line.split(": ", 1) for line in lines)
    return fields.get("id"), fields["event"], json.loads(fields["data"])


async def test_the_snapshot_comes_first_then_the_stored_events_in_order() -> None:
    source = FakeSource(view_with())
    source.stored = [event("stage.started"), event("stage.completed")]

    frames = await collect(source, FakeEvents(), polls=0)

    assert decode(frames[0])[1] == "snapshot"
    assert decode(frames[0])[2]["status"] == "planning"
    replayed = [decode(frame) for frame in frames[1:]]
    assert [item[1] for item in replayed] == ["job_event", "job_event"]
    assert [item[0] for item in replayed] == [str(message.id) for message in source.stored]
    assert [item[2]["type"] for item in replayed] == ["stage.started", "stage.completed"]


async def test_the_subscription_is_opened_before_the_replay_query() -> None:
    events = FakeEvents()
    source = FakeSource(view_with(), events)

    await collect(source, events, polls=0)

    assert source.subscriptions_at_query[0] == 1


async def test_only_events_after_the_last_event_id_are_replayed() -> None:
    source = FakeSource(view_with())
    source.stored = [event("a.one"), event("a.two"), event("a.three")]

    frames = await collect(source, FakeEvents(), after=source.stored[0].id, polls=0)

    assert [decode(frame)[2]["type"] for frame in frames[1:]] == ["a.two", "a.three"]


async def test_a_live_message_already_replayed_is_not_sent_twice() -> None:
    source = FakeSource(view_with())
    events = FakeEvents()
    replayed = event("stage.started")
    source.stored = [replayed]
    events.pubsub.queue = [replayed, event("stage.completed")]

    frames = await collect(source, events, polls=3)

    assert [decode(frame)[2]["type"] for frame in frames[1:]] == ["stage.started", "stage.completed"]


async def test_a_transient_message_is_sent_without_an_id() -> None:
    source = FakeSource(view_with("rendering"))
    events = FakeEvents()
    events.pubsub.queue = [JobMessage(id=None, type="render.progress", stage="render", payload={"progress": 3}, at=AT)]

    frames = await collect(source, events, polls=2)

    identifier, name, data = decode(frames[1])
    assert (identifier, name, data["type"]) == (None, "job_event", "render.progress")
    assert frames[1].startswith(b"event: job_event")


async def test_the_stream_ends_after_a_terminal_live_message() -> None:
    source = FakeSource(view_with("rendering"))
    events = FakeEvents()
    events.pubsub.queue = [event("stage.started"), event("job.completed"), event("never.sent")]

    frames = await collect(source, events, polls=10)

    assert [decode(frame)[2]["type"] for frame in frames[1:]] == ["stage.started", "job.completed"]


async def test_a_finished_job_replays_its_events_and_ends_without_waiting() -> None:
    source = FakeSource(view_with("completed"))
    source.stored = [event("stage.started"), event("job.completed")]

    frames = await collect(source, FakeEvents(), polls=10)

    assert [decode(frame)[2]["type"] for frame in frames[1:]] == ["stage.started", "job.completed"]


async def test_a_finished_job_without_events_sends_only_the_snapshot() -> None:
    source = FakeSource(view_with("failed"))

    frames = await collect(source, FakeEvents(), polls=10)

    assert len(frames) == 1


async def test_the_periodic_recheck_delivers_events_that_were_never_published() -> None:
    source = FakeSource(view_with())
    events = FakeEvents()
    frames_task = asyncio.create_task(collect(source, events, polls=40, recheck=0.0))
    await asyncio.sleep(0.005)
    source.stored.append(event("job.cancel_requested"))
    source.stored.append(event("job.cancelled"))
    source.finish(JobStatus.CANCELLED)

    frames = await frames_task

    assert [decode(frame)[2]["type"] for frame in frames[1:]] == ["job.cancel_requested", "job.cancelled"]


async def test_a_terminal_job_state_ends_the_stream_at_the_recheck() -> None:
    source = FakeSource(view_with())
    task = asyncio.create_task(collect(source, FakeEvents(), polls=1_000, recheck=0.0))
    await asyncio.sleep(0.005)
    source.finish(JobStatus.FAILED)

    frames = await asyncio.wait_for(task, 5)

    assert len(frames) == 1


async def test_a_heartbeat_comment_is_sent_when_nothing_else_is() -> None:
    source = FakeSource(view_with())

    frames = await collect(source, FakeEvents(), polls=20, heartbeat=0.0, recheck=1_000)

    assert HEARTBEAT_FRAME in frames


async def test_the_lease_is_released_when_the_client_leaves() -> None:
    lease = FakeLease()

    await collect(FakeSource(view_with()), FakeEvents(), polls=2, lease=lease)

    assert lease.released == 1


async def test_the_lease_is_released_when_the_job_is_gone() -> None:
    source = FakeSource(view_with())
    source.missing = True
    lease = FakeLease()

    frames = await collect(source, FakeEvents(), lease=lease)

    assert frames == []
    assert lease.released == 1


def test_a_valid_last_event_id_is_parsed_and_a_bad_one_is_ignored() -> None:
    identifier = new_id()

    assert parse_last_event_id(f" {identifier} ") == identifier
    assert parse_last_event_id("not-a-uuid") is None
    assert parse_last_event_id("") is None
    assert parse_last_event_id(None) is None


def test_a_frame_carries_the_event_id_and_one_json_line() -> None:
    message = event("scene.voiced", {"sceneId": "intro", "durationMs": 1200})

    frame = message_frame(message).decode()

    assert frame.startswith(f"id: {message.id}\nevent: job_event\ndata: ")
    assert frame.endswith("\n\n")
    assert frame.count("\n") == 4


@pytest.mark.parametrize("raw", [b"not json", b"{}", b'{"id": "x"}'])
def test_a_malformed_live_message_is_dropped(raw: bytes) -> None:
    assert JobMessage.from_json(raw) is None


async def never_disconnected() -> bool:
    return False


async def test_a_long_stream_ends_with_a_reconnect_frame_so_the_client_authenticates_again() -> None:
    source = FakeSource(view_with("rendering"))
    lease = FakeLease()

    stream = stream_job_events(
        source,
        FakeEvents(),
        new_id(),
        after=None,
        is_disconnected=never_disconnected,
        lease=lease,
        poll_seconds=0.001,
        max_seconds=0.02,
    )
    frames = [frame async for frame in stream]

    assert decode(frames[0])[1] == "snapshot"
    assert frames[-1] == RECONNECT_FRAME
    assert decode(frames[-1])[1:] == ("reconnect", {})
    assert lease.released == 1


async def test_a_stream_inside_its_time_limit_never_sends_a_reconnect_frame() -> None:
    source = FakeSource(view_with("rendering"))

    frames = await collect(source, FakeEvents(), polls=3)

    assert RECONNECT_FRAME not in frames


def test_the_default_stream_limit_is_fifteen_minutes() -> None:
    assert MAX_STREAM_SECONDS == 900.0
