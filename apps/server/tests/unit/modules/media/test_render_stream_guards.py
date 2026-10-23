import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fakeredis.aioredis import FakeRedis
from tests.fakes.storage import InMemoryStorage
from tests.unit.modules.media.render_support import Rig, build_rig
from tests.unit.modules.media.support import USER_A, USER_B

from motionile.core.clock import FrozenClock
from motionile.core.redis import RedisKeyBuilder, RedisStore
from motionile.modules.media import MediaService, PresignedDelivery
from motionile.modules.media.exceptions import TooManyStreamsError
from motionile.modules.media.render_stream import StreamGuards, stream_render_events
from motionile.modules.media.stream_slots import MAX_STREAMS_PER_USER, StreamSlots

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(NOW)


@pytest.fixture
def slots(clock: FrozenClock) -> StreamSlots:
    return StreamSlots(RedisStore(FakeRedis(), RedisKeyBuilder("t")), clock)


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return build_rig(tmp_path / "work")


async def never_disconnected() -> bool:
    return False


async def test_a_user_can_hold_up_to_the_limit_of_streams(slots: StreamSlots) -> None:
    leases = [await slots.acquire(USER_A) for _ in range(MAX_STREAMS_PER_USER)]

    with pytest.raises(TooManyStreamsError) as raised:
        await slots.acquire(USER_A)

    assert raised.value.status_code == 429
    assert raised.value.code == "too_many_streams"
    assert len(leases) == MAX_STREAMS_PER_USER


async def test_the_limit_is_per_user(slots: StreamSlots) -> None:
    for _ in range(MAX_STREAMS_PER_USER):
        await slots.acquire(USER_A)

    await slots.acquire(USER_B)


async def test_a_rejected_attempt_does_not_consume_a_slot(slots: StreamSlots) -> None:
    leases = [await slots.acquire(USER_A) for _ in range(MAX_STREAMS_PER_USER)]
    for _ in range(3):
        with pytest.raises(TooManyStreamsError):
            await slots.acquire(USER_A)

    await leases[0].release()

    await slots.acquire(USER_A)
    with pytest.raises(TooManyStreamsError):
        await slots.acquire(USER_A)


async def test_releasing_a_lease_frees_its_slot_and_is_idempotent(slots: StreamSlots) -> None:
    leases = [await slots.acquire(USER_A) for _ in range(MAX_STREAMS_PER_USER)]

    await leases[0].release()
    await leases[0].release()
    await slots.acquire(USER_A)

    with pytest.raises(TooManyStreamsError):
        await slots.acquire(USER_A)


async def test_an_unrenewed_lease_expires_and_a_renewed_one_does_not(clock: FrozenClock, slots: StreamSlots) -> None:
    leases = [await slots.acquire(USER_A) for _ in range(MAX_STREAMS_PER_USER)]
    clock.set(NOW + timedelta(seconds=60))
    await leases[0].renew()
    clock.set(NOW + timedelta(seconds=100))

    for _ in range(MAX_STREAMS_PER_USER - 1):
        await slots.acquire(USER_A)
    with pytest.raises(TooManyStreamsError):
        await slots.acquire(USER_A)


class Switch:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.checks = 0

    async def __call__(self) -> bool:
        self.checks += 1
        return self.allowed


def stream_with(rig: Rig, guards: StreamGuards, render_id: UUID, **options: float) -> AsyncGenerator[bytes]:
    return stream_render_events(
        rig.world.transaction,
        MediaService(PresignedDelivery(InMemoryStorage(), timedelta(seconds=60)), rig.world.render_store),
        rig.events,
        USER_A,
        render_id,
        is_disconnected=never_disconnected,
        guards=guards,
        **options,
    )


async def drain(stream: AsyncIterator[bytes]) -> list[bytes]:
    return [frame async for frame in stream]


async def test_a_revoked_permission_ends_the_stream_before_the_snapshot(rig: Rig, slots: StreamSlots) -> None:
    render_id = await rig.queue_render()
    rig.render(render_id).status = "voicing"
    lease = await slots.acquire(USER_A)

    frames = await asyncio.wait_for(drain(stream_with(rig, StreamGuards(Switch(False), lease), render_id)), 5)

    assert frames == []


async def test_a_permission_revoked_mid_stream_ends_it_at_the_next_recheck(rig: Rig, slots: StreamSlots) -> None:
    render_id = await rig.queue_render()
    rig.render(render_id).status = "voicing"
    switch = Switch()
    lease = await slots.acquire(USER_A)
    stream = stream_with(
        rig, StreamGuards(switch, lease), render_id, poll_seconds=0.02, recheck_seconds=0.1, heartbeat_seconds=0.05
    )
    frames: list[bytes] = []

    async def consume() -> None:
        async for frame in stream:
            frames.append(frame)
            if len(frames) == 2:
                switch.allowed = False

    await asyncio.wait_for(consume(), 5)

    assert frames[0].startswith(b"event: snapshot")
    assert 2 <= len(frames) <= 8
    assert switch.checks >= 2


async def test_the_lease_is_released_when_the_stream_ends(rig: Rig, slots: StreamSlots) -> None:
    render_id = await rig.queue_render()
    rig.render(render_id).status = "completed"
    rig.render(render_id).progress = 100
    others = [await slots.acquire(USER_A) for _ in range(MAX_STREAMS_PER_USER - 1)]
    lease = await slots.acquire(USER_A)

    frames = await asyncio.wait_for(drain(stream_with(rig, StreamGuards(Switch(), lease), render_id)), 5)

    assert len(frames) == 1
    await slots.acquire(USER_A)
    assert len(others) == MAX_STREAMS_PER_USER - 1


async def test_the_lease_is_released_when_the_client_closes_the_stream(rig: Rig, slots: StreamSlots) -> None:
    render_id = await rig.queue_render()
    rig.render(render_id).status = "voicing"
    for _ in range(MAX_STREAMS_PER_USER - 1):
        await slots.acquire(USER_A)
    lease = await slots.acquire(USER_A)
    stream = stream_with(rig, StreamGuards(Switch(), lease), render_id, poll_seconds=0.02)

    assert (await anext(stream)).startswith(b"event: snapshot")
    await stream.aclose()

    await slots.acquire(USER_A)
