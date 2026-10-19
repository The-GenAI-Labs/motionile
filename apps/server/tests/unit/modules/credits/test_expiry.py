from datetime import timedelta

import pytest
from tests.unit.modules.credits.conftest import Harness

from motionile.core.ids import new_id
from motionile.modules.credits import InsufficientCreditsError


async def test_expired_credits_cannot_be_reserved_before_any_sweep_runs(harness: Harness) -> None:
    await harness.grant(50, expires_in=timedelta(days=1))
    harness.clock.advance(timedelta(days=1, seconds=1))

    with pytest.raises(InsufficientCreditsError) as raised:
        await harness.reserve(1)

    assert (raised.value.available, raised.value.required) == (0, 1)


async def test_reserve_expires_due_lots_inside_the_same_operation(harness: Harness) -> None:
    expiring = await harness.grant(40, expires_in=timedelta(days=1))
    await harness.grant(60)
    harness.clock.advance(timedelta(days=2))

    await harness.reserve(60)

    assert harness.wallet() == (60, 60)
    lot = harness.store.lots[expiring.lot_id]
    assert (lot.remaining, lot.expired_at) == (0, harness.clock.now())
    assert harness.ledger() == [("purchase", 40, 0), ("purchase", 60, 0), ("expiry", -40, 0), ("reserve", 0, 60)]
    entry = harness.store.ledger[2]
    assert (entry.ref_type, entry.ref_id) == ("lot", expiring.lot_id)


async def test_commit_expires_due_lots_before_consuming(harness: Harness) -> None:
    forever = await harness.grant(100)
    reservation = await harness.reserve(10)
    stale = await harness.grant(30, expires_in=timedelta(days=1))
    harness.clock.advance(timedelta(days=2))

    result = await harness.service.commit(harness.session, reservation.id, 10, "commit:lazy")

    assert harness.lot_remaining(stale.lot_id) == 0
    assert harness.lot_remaining(forever.lot_id) == 90
    assert [item.lot_id for item in result.allocations] == [forever.lot_id]
    assert [row[0] for row in harness.ledger()[-2:]] == ["expiry", "commit"]
    assert harness.wallet() == (90, 0)


async def test_credits_held_by_a_reservation_are_not_expired(harness: Harness) -> None:
    lot = await harness.grant(100, expires_in=timedelta(days=1))
    reservation = await harness.reserve(60, ttl=timedelta(days=10))
    harness.clock.advance(timedelta(days=2))

    result = await harness.service.expire_due_lots(harness.session, harness.user_id)

    assert result.expired == 40
    assert harness.wallet() == (60, 60)
    stored = harness.store.lots[lot.lot_id]
    assert (stored.remaining, stored.expired_at) == (60, None)

    await harness.service.release(harness.session, reservation.id, "release:held")
    assert (await harness.service.expire_due_lots(harness.session, harness.user_id)).expired == 60
    assert harness.wallet() == (0, 0)
    assert harness.store.lots[lot.lot_id].expired_at == harness.clock.now()


async def test_a_committed_reservation_spends_expired_but_held_credits_first(harness: Harness) -> None:
    expiring = await harness.grant(50, expires_in=timedelta(days=1))
    forever = await harness.grant(20)
    reservation = await harness.reserve(30, ttl=timedelta(days=10))
    harness.clock.advance(timedelta(days=2))

    result = await harness.service.commit(harness.session, reservation.id, 30, "commit:held")

    assert [(item.lot_id, item.amount) for item in result.allocations] == [(expiring.lot_id, 10), (forever.lot_id, 20)]
    assert harness.ledger()[-2:] == [("expiry", -40, 0), ("commit", -30, -30)]
    assert harness.lot_remaining(expiring.lot_id) == 0
    assert harness.lot_remaining(forever.lot_id) == 0
    assert harness.wallet() == (0, 0)


async def test_expiry_takes_lots_in_order_and_stops_at_the_available_amount(harness: Harness) -> None:
    first = await harness.grant(30, expires_in=timedelta(days=1))
    second = await harness.grant(30, expires_in=timedelta(days=2))
    third = await harness.grant(30, expires_in=timedelta(days=3))
    await harness.reserve(50, ttl=timedelta(days=30))
    harness.clock.advance(timedelta(days=10))

    result = await harness.service.expire_due_lots(harness.session, harness.user_id)

    assert result.expired == 40
    assert harness.lot_remaining(first.lot_id) == 0
    assert harness.lot_remaining(second.lot_id) == 20
    assert harness.lot_remaining(third.lot_id) == 30
    assert harness.store.lots[second.lot_id].expired_at is None
    assert harness.wallet() == (50, 50)


async def test_expiry_is_idempotent_and_uses_unique_ledger_keys(harness: Harness) -> None:
    await harness.grant(10, expires_in=timedelta(days=1))
    await harness.grant(20, expires_in=timedelta(days=1))
    harness.clock.advance(timedelta(days=2))

    first = await harness.service.expire_due_lots(harness.session, harness.user_id)
    second = await harness.service.expire_due_lots(harness.session, harness.user_id)

    assert (first.expired, second.expired) == (30, 0)
    keys = [entry.idempotency_key for entry in harness.store.ledger if entry.reason == "expiry"]
    assert len(keys) == len(set(keys)) == 2
    assert all(key.startswith("expiry:") for key in keys)


async def test_expiry_for_a_user_without_a_wallet_does_nothing(harness: Harness) -> None:
    result = await harness.service.expire_due_lots(harness.session, harness.user_id)

    assert result.expired == 0
    assert harness.store.wallets == {}


async def test_users_due_for_expiry_ignores_fully_held_and_unexpired_wallets(harness: Harness) -> None:
    held_user, fresh_user = new_id(), new_id()
    await harness.grant(10, expires_in=timedelta(days=1))
    await harness.grant(10, expires_in=timedelta(days=1), user_id=held_user)
    await harness.grant(10, expires_in=timedelta(days=30), user_id=fresh_user)
    await harness.reserve(10, user_id=held_user, ttl=timedelta(days=30))
    harness.clock.advance(timedelta(days=2))

    assert await harness.service.users_due_for_expiry(harness.session, None, 10) == [harness.user_id]
    assert await harness.service.users_due_for_expiry(harness.session, harness.user_id, 10) == []


async def test_users_due_for_expiry_is_keyset_paginated(harness: Harness) -> None:
    users = sorted(new_id() for _ in range(5))
    for user in users:
        await harness.grant(5, expires_in=timedelta(days=1), user_id=user)
    harness.clock.advance(timedelta(days=2))

    first = await harness.service.users_due_for_expiry(harness.session, None, 2)
    second = await harness.service.users_due_for_expiry(harness.session, first[-1], 2)
    third = await harness.service.users_due_for_expiry(harness.session, second[-1], 2)

    assert first + second + third == users
