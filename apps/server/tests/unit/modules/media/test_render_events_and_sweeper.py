import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from tests.fakes.storage import InMemoryStorage
from tests.unit.modules.media.render_support import Rig, build_rig
from tests.unit.modules.media.support import USER_A, USER_B

from motionile.core.clock import FrozenClock
from motionile.core.ratelimit.policies import DEFAULT_POLICIES
from motionile.core.redis import RedisKeyBuilder
from motionile.modules.media import MediaService, PresignedDelivery, RenderNotFoundError, RenderStatus
from motionile.modules.media.pipeline import fail_stalled_renders
from motionile.modules.media.render_events import RenderProgress, cancel_flag_key, render_channel
from motionile.modules.media.render_stream import HEARTBEAT_FRAME, sse_frame, stream_render_events

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return build_rig(tmp_path / "work")


def message(render_id: UUID, status: RenderStatus, progress: int = 10) -> RenderProgress:
    return RenderProgress(render_id=render_id, status=status, progress=progress, at=NOW)


def service(rig: Rig) -> MediaService:
    return MediaService(PresignedDelivery(InMemoryStorage(), timedelta(seconds=60)), rig.world.render_store)


async def never_disconnected() -> bool:
    return False


def test_channel_and_flag_names_use_the_key_builder() -> None:
    keys = RedisKeyBuilder("mo")
    render_id = UUID(int=1)

    assert render_channel(keys, render_id) == f"mo:render:{render_id}"
    assert cancel_flag_key(keys, render_id) == f"mo:render.cancel:{render_id}"


def test_a_progress_message_serializes_in_camel_case_without_empty_errors() -> None:
    payload = json.loads(message(UUID(int=1), RenderStatus.CAPTURING, 42).to_json())

    assert set(payload) == {"renderId", "status", "stage", "progress", "at"}
    assert payload["status"] == "capturing"
    assert payload["stage"] is None


def test_a_failed_message_carries_the_error() -> None:
    failed = RenderProgress(
        render_id=UUID(int=1),
        status=RenderStatus.FAILED,
        progress=30,
        at=NOW,
        error_code="timeout",
        error_message="slow",
    )

    assert json.loads(failed.to_json())["errorCode"] == "timeout"
    assert failed.is_terminal
    assert RenderProgress.from_json("not json") is None


async def test_published_messages_reach_a_subscriber(rig: Rig) -> None:
    render_id = UUID(int=1)
    async with rig.events.subscribe(render_id) as subscription:
        await rig.events.publish(message(render_id, RenderStatus.VOICING, 12))
        received = None
        for _ in range(3):
            received = await subscription.next(0.2)
            if received is not None:
                break

    assert received is not None
    assert received.progress == 12


async def test_the_cancel_flag_round_trips(rig: Rig) -> None:
    render_id = UUID(int=2)
    assert not await rig.events.cancel_flagged(render_id)

    await rig.events.flag_cancel(render_id)

    assert await rig.events.cancel_flagged(render_id)
    assert not await rig.events.cancel_flagged(UUID(int=3))


async def test_the_sweeper_fails_only_stalled_active_renders(rig: Rig) -> None:
    stalled = await rig.queue_render()
    fresh = await rig.queue_render()
    done = await rig.queue_render()
    rig.render(stalled).status = "capturing"
    rig.render(stalled).updated_at = NOW - timedelta(minutes=30)
    rig.render(fresh).updated_at = NOW - timedelta(minutes=1)
    rig.render(done).status = "completed"
    rig.render(done).updated_at = NOW - timedelta(hours=3)
    clock = FrozenClock(NOW)

    async with rig.events.subscribe(stalled) as subscription:
        failed = await fail_stalled_renders(rig.world.transaction, rig.job_store, rig.events, clock, 900)
        received = None
        for _ in range(3):
            received = await subscription.next(0.2)
            if received is not None:
                break

    assert failed == 1
    assert rig.render(stalled).status == "failed"
    assert rig.render(stalled).error_code == "render_stalled"
    assert rig.render(stalled).completed_at == NOW
    assert rig.render(fresh).status == "queued"
    assert rig.render(done).status == "completed"
    assert received is not None
    assert received.status is RenderStatus.FAILED


async def test_the_sweeper_gives_up_on_a_render_that_never_started(rig: Rig) -> None:
    render_id = await rig.queue_render()
    rig.render(render_id).updated_at = NOW - timedelta(hours=2)

    failed = await fail_stalled_renders(rig.world.transaction, rig.job_store, rig.events, FrozenClock(NOW), 900)

    assert failed == 1
    assert rig.render(render_id).status == "failed"


async def test_the_sweeper_is_quiet_when_nothing_is_stalled(rig: Rig) -> None:
    assert await fail_stalled_renders(rig.world.transaction, rig.job_store, rig.events, FrozenClock(NOW), 900) == 0


def test_sse_frames_follow_the_event_stream_format() -> None:
    assert sse_frame("progress", '{"a":1}') == b'event: progress\ndata: {"a":1}\n\n'
    assert HEARTBEAT_FRAME == b": heartbeat\n\n"


async def collect_stream(rig: Rig, render_id: UUID, user_id: UUID, poll_seconds: float = 1.0) -> list[bytes]:
    frames: list[bytes] = []
    stream = stream_render_events(
        rig.world.transaction,
        service(rig),
        rig.events,
        user_id,
        render_id,
        is_disconnected=never_disconnected,
        poll_seconds=poll_seconds,
    )
    async for frame in stream:
        frames.append(frame)
    return frames


async def test_a_stream_for_a_finished_render_sends_the_snapshot_and_ends(rig: Rig) -> None:
    render_id = await rig.queue_render()
    rig.render(render_id).status = "completed"
    rig.render(render_id).progress = 100

    frames = await asyncio.wait_for(collect_stream(rig, render_id, USER_A), 5)

    assert len(frames) == 1
    assert frames[0].startswith(b"event: snapshot\n")
    assert json.loads(frames[0].split(b"data: ")[1])["status"] == "completed"


async def test_a_stream_sends_snapshot_progress_and_stops_after_the_terminal_message(rig: Rig) -> None:
    render_id = await rig.queue_render()
    rig.render(render_id).status = "voicing"

    async def publish_later() -> None:
        await asyncio.sleep(0.3)
        await rig.events.publish(message(render_id, RenderStatus.MIXING, 30))
        await rig.events.publish(message(render_id, RenderStatus.COMPLETED, 100))

    publisher = asyncio.ensure_future(publish_later())
    frames = await asyncio.wait_for(collect_stream(rig, render_id, USER_A, poll_seconds=0.1), 5)
    await publisher

    events = [frame.split(b"\n")[0] for frame in frames]
    assert events == [b"event: snapshot", b"event: progress", b"event: progress"]
    assert json.loads(frames[-1].split(b"data: ")[1])["status"] == "completed"


async def test_a_quiet_stream_sends_heartbeat_comments(rig: Rig) -> None:
    render_id = await rig.queue_render()
    rig.render(render_id).status = "voicing"
    frames: list[bytes] = []
    stream = stream_render_events(
        rig.world.transaction,
        service(rig),
        rig.events,
        USER_A,
        render_id,
        is_disconnected=never_disconnected,
        heartbeat_seconds=0.2,
        poll_seconds=0.05,
    )

    async def take() -> None:
        async for frame in stream:
            frames.append(frame)
            if len(frames) == 3:
                return

    await asyncio.wait_for(take(), 5)
    await stream.aclose()

    assert frames[1:] == [HEARTBEAT_FRAME, HEARTBEAT_FRAME]


async def test_the_stream_stops_when_the_client_disconnects(rig: Rig) -> None:
    render_id = await rig.queue_render()
    rig.render(render_id).status = "voicing"
    polls = 0

    async def disconnected_after_two_polls() -> bool:
        nonlocal polls
        polls += 1
        return polls > 2

    stream = stream_render_events(
        rig.world.transaction,
        service(rig),
        rig.events,
        USER_A,
        render_id,
        is_disconnected=disconnected_after_two_polls,
        poll_seconds=0.05,
    )
    frames = await asyncio.wait_for(_drain(stream), 5)

    assert len(frames) == 1
    assert polls == 3


async def _drain(stream: AsyncIterator[bytes]) -> list[bytes]:
    return [frame async for frame in stream]


async def test_a_stream_for_another_users_render_is_a_not_found(rig: Rig) -> None:
    render_id = await rig.queue_render()

    with pytest.raises(RenderNotFoundError):
        await collect_stream(rig, render_id, USER_B)


def test_the_render_create_policy_allows_ten_per_hour_per_user() -> None:
    policy = next(policy for policy in DEFAULT_POLICIES if policy.name == "render.create")

    assert [(rule.limit, rule.window_seconds, rule.scope.value) for rule in policy.rules] == [(10, 3600, "user")]
