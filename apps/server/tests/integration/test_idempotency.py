import asyncio
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select
from tests.fakes.resources import FIXED_NOW

from motionile.core.clock import FrozenClock
from motionile.core.db import Database
from motionile.core.idempotency import (
    Claimed,
    IdempotencyInProgressError,
    IdempotencyKeyReusedError,
    IdempotencyRecord,
    IdempotencyScope,
    IdempotencyService,
    Replay,
    StoredResponse,
    request_fingerprint,
)
from motionile.core.ids import new_id

CONCURRENT_CLAIMS = 25
HASH_A = request_fingerprint("POST", "/v1/things", b'{"a":1}')
HASH_B = request_fingerprint("POST", "/v1/things", b'{"a":2}')


def service_at(database: Database, clock: FrozenClock) -> IdempotencyService:
    return IdempotencyService(
        database=database, clock=clock, ttl=timedelta(hours=24), lock_duration=timedelta(seconds=30)
    )


def scope_for(key: str, user_id: UUID | None = None) -> IdempotencyScope:
    return IdempotencyScope(scope="tests.things", user_id=user_id, key=key)


async def count_records(database: Database) -> int:
    async with database.session() as session:
        return (await session.execute(select(func.count()).select_from(IdempotencyRecord))).scalar_one()


async def test_claim_complete_and_replay(database: Database) -> None:
    service = service_at(database, FrozenClock(FIXED_NOW))
    target = scope_for("key-a")

    claimed = await service.begin(target, HASH_A)
    assert isinstance(claimed, Claimed)
    with pytest.raises(IdempotencyInProgressError) as in_progress:
        await service.begin(target, HASH_A)
    await service.complete(claimed.record_id, StoredResponse(201, {"id": "x"}, {"Location": "/x"}))
    replay = await service.begin(target, HASH_A)

    assert in_progress.value.headers["Retry-After"] == "30"
    assert isinstance(replay, Replay)
    assert replay.response == StoredResponse(201, {"id": "x"}, {"Location": "/x"})


async def test_rejects_reuse_with_a_different_request(database: Database) -> None:
    service = service_at(database, FrozenClock(FIXED_NOW))
    target = scope_for("key-b")

    claimed = await service.begin(target, HASH_A)
    assert isinstance(claimed, Claimed)
    await service.complete(claimed.record_id, StoredResponse(200, {}, {}))

    with pytest.raises(IdempotencyKeyReusedError):
        await service.begin(target, HASH_B)


async def test_exactly_one_concurrent_claim_wins(database: Database) -> None:
    service = service_at(database, FrozenClock(FIXED_NOW))
    target = scope_for("key-concurrent")

    outcomes = await asyncio.gather(
        *(service.begin(target, HASH_A) for _ in range(CONCURRENT_CLAIMS)), return_exceptions=True
    )

    claimed = [outcome for outcome in outcomes if isinstance(outcome, Claimed)]
    in_progress = [outcome for outcome in outcomes if isinstance(outcome, IdempotencyInProgressError)]
    assert len(claimed) == 1
    assert len(in_progress) == CONCURRENT_CLAIMS - 1
    assert await count_records(database) == 1


async def test_stale_lock_is_reclaimed_only_by_the_same_request(database: Database) -> None:
    clock = FrozenClock(FIXED_NOW)
    service = service_at(database, clock)
    target = scope_for("key-stale")
    first = await service.begin(target, HASH_A)
    assert isinstance(first, Claimed)

    clock.advance(timedelta(seconds=31))

    with pytest.raises(IdempotencyKeyReusedError):
        await service.begin(target, HASH_B)
    second = await service.begin(target, HASH_A)
    assert isinstance(second, Claimed)
    assert second.record_id == first.record_id


async def test_expired_records_free_the_key(database: Database) -> None:
    clock = FrozenClock(FIXED_NOW)
    service = service_at(database, clock)
    target = scope_for("key-expired")
    first = await service.begin(target, HASH_A)
    assert isinstance(first, Claimed)
    await service.complete(first.record_id, StoredResponse(200, {}, {}))

    clock.advance(timedelta(hours=25))

    assert isinstance(await service.begin(target, HASH_B), Claimed)


async def test_release_frees_the_key(database: Database) -> None:
    service = service_at(database, FrozenClock(FIXED_NOW))
    target = scope_for("key-release")
    first = await service.begin(target, HASH_A)
    assert isinstance(first, Claimed)

    await service.release(first.record_id)

    assert isinstance(await service.begin(target, HASH_B), Claimed)


async def test_keys_are_scoped_per_user_and_null_users_collide(database: Database) -> None:
    service = service_at(database, FrozenClock(FIXED_NOW))

    first_user = await service.begin(scope_for("shared", new_id()), HASH_A)
    second_user = await service.begin(scope_for("shared", new_id()), HASH_A)
    anonymous = await service.begin(scope_for("shared"), HASH_A)

    assert isinstance(first_user, Claimed)
    assert isinstance(second_user, Claimed)
    assert isinstance(anonymous, Claimed)
    with pytest.raises(IdempotencyInProgressError):
        await service.begin(scope_for("shared"), HASH_A)
