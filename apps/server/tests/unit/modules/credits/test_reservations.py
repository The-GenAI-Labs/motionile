from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.unit.modules.credits.conftest import Harness

from motionile.core.errors import PROBLEM_MEDIA_TYPE, register_exception_handlers
from motionile.core.ids import new_id
from motionile.modules.credits import (
    CommitExceedsReservationError,
    IdempotencyKeyConflictError,
    InsufficientCreditsError,
    InvalidCreditAmountError,
    InvalidCreditReferenceError,
    ReservationAlreadyActiveError,
    ReservationNotActiveError,
    ReservationNotFoundError,
    ReserveCommand,
)


async def test_reserve_holds_credits_without_touching_lots(harness: Harness) -> None:
    grant = await harness.grant(100)

    reservation = await harness.reserve(30)

    assert harness.wallet() == (100, 30)
    assert harness.lot_remaining(grant.lot_id) == 100
    assert harness.ledger()[-1] == ("reserve", 0, 30)
    assert reservation.amount == 30
    assert reservation.reserved_after == 30
    stored = harness.store.reservations[reservation.id]
    assert (stored.status, stored.committed_amount, stored.settled_at) == ("active", None, None)


async def test_reserve_ttl_defaults_from_billing_settings_and_can_be_overridden(harness: Harness) -> None:
    await harness.grant(100)

    default = await harness.reserve(10)
    custom = await harness.reserve(10, ttl=timedelta(minutes=5))

    assert default.expires_at == harness.clock.now() + timedelta(seconds=3_600)
    assert custom.expires_at == harness.clock.now() + timedelta(minutes=5)


async def test_reserve_beyond_available_credits_fails_with_the_amounts(harness: Harness) -> None:
    await harness.grant(100)
    await harness.reserve(70)

    with pytest.raises(InsufficientCreditsError) as raised:
        await harness.reserve(31)

    error = raised.value
    assert (error.status_code, error.code) == (402, "insufficient_credits")
    assert (error.available, error.required) == (30, 31)
    assert harness.wallet() == (100, 70)


async def test_insufficient_credits_problem_body_carries_available_and_required() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/needs-credits")
    async def needs_credits() -> None:
        raise InsufficientCreditsError(available=10, required=25)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/needs-credits")

    assert response.status_code == 402
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    body = response.json()
    assert body["code"] == "insufficient_credits"
    assert body["type"] == "urn:motionile:problem:insufficient_credits"
    assert (body["available"], body["required"]) == (10, 25)


async def test_reserve_without_a_wallet_reports_zero_available(harness: Harness) -> None:
    with pytest.raises(InsufficientCreditsError) as raised:
        await harness.reserve(1)

    assert (raised.value.available, raised.value.required) == (0, 1)
    assert harness.store.wallets == {}


async def test_only_one_active_reservation_may_exist_per_reference(harness: Harness) -> None:
    await harness.grant(100)
    job = new_id()
    first = await harness.reserve(10, ref_id=job)

    with pytest.raises(ReservationAlreadyActiveError) as raised:
        await harness.reserve(10, ref_id=job)

    assert raised.value.status_code == 409
    assert harness.wallet() == (100, 10)
    await harness.service.release(harness.session, first.id, "release:first")
    again = await harness.reserve(10, ref_id=job)
    assert again.id != first.id


async def test_reserve_replay_returns_the_original_even_after_it_settled(harness: Harness) -> None:
    await harness.grant(100)
    job = new_id()
    first = await harness.reserve(40, key="reserve:job", ref_id=job)
    await harness.service.commit(harness.session, first.id, 25, "commit:job")
    before = (list(harness.store.ledger), dict(harness.store.wallets), dict(harness.store.reservations))

    again = await harness.reserve(40, key="reserve:job", ref_id=job)

    assert again == first
    assert (harness.store.ledger, harness.store.wallets, harness.store.reservations) == before


@pytest.mark.parametrize("amount", [0, -1])
async def test_reserve_rejects_non_positive_amounts(harness: Harness, amount: int) -> None:
    with pytest.raises(InvalidCreditAmountError):
        await harness.reserve(amount)


async def test_reserve_rejects_malformed_references_and_ttls(harness: Harness, session: AsyncSession) -> None:
    await harness.grant(10)
    base = ReserveCommand(user_id=harness.user_id, amount=1, ref_type="job", ref_id=new_id(), key="r")

    with pytest.raises(InvalidCreditReferenceError):
        await harness.service.reserve(session, replace(base, ref_type="Job!"))
    with pytest.raises(InvalidCreditAmountError) as raised:
        await harness.service.reserve(session, replace(base, ttl=timedelta(seconds=-1)))
    assert raised.value.code == "invalid_reservation_ttl"


async def test_reserve_key_reuse_for_another_operation_conflicts(harness: Harness) -> None:
    await harness.grant(10, key="same")

    with pytest.raises(IdempotencyKeyConflictError):
        await harness.reserve(5, key="same")


async def test_commit_consumes_soonest_expiring_lots_first_and_non_expiring_last(harness: Harness) -> None:
    forever = await harness.grant(50)
    late = await harness.grant(50, expires_in=timedelta(days=20))
    soon_first = await harness.grant(30, expires_in=timedelta(days=2))
    soon_second = await harness.grant(30, expires_in=timedelta(days=2))
    reservation = await harness.reserve(100)

    result = await harness.service.commit(harness.session, reservation.id, 100, "commit:order")

    assert [(item.lot_id, item.amount) for item in result.allocations] == [
        (soon_first.lot_id, 30),
        (soon_second.lot_id, 30),
        (late.lot_id, 40),
    ]
    assert harness.lot_remaining(forever.lot_id) == 50
    assert harness.lot_remaining(late.lot_id) == 10
    assert harness.wallet() == (60, 0)


async def test_lots_with_equal_expiry_are_consumed_by_creation_then_id(harness: Harness) -> None:
    first = await harness.grant(10, expires_in=timedelta(days=1))
    harness.clock.advance(timedelta(seconds=1))
    second = await harness.grant(10, expires_in=timedelta(days=1) - timedelta(seconds=1))
    reservation = await harness.reserve(15)

    result = await harness.service.commit(harness.session, reservation.id, 15, "commit:ties")

    assert [item.lot_id for item in result.allocations] == [first.lot_id, second.lot_id]
    assert [item.amount for item in result.allocations] == [10, 5]


async def test_partial_commit_charges_actual_and_releases_the_rest_in_one_row(harness: Harness) -> None:
    grant = await harness.grant(100)
    reservation = await harness.reserve(60)

    result = await harness.service.commit(harness.session, reservation.id, 25, "commit:partial")

    assert (result.charged, result.released) == (25, 35)
    assert (result.balance_after, result.reserved_after) == (75, 0)
    assert harness.wallet() == (75, 0)
    assert harness.lot_remaining(grant.lot_id) == 75
    assert harness.ledger()[-1] == ("commit", -25, -60)
    entry = harness.store.ledger[-1]
    assert entry.metadata["allocations"] == [{"lotId": str(grant.lot_id), "amount": 25}]
    assert (entry.ref_type, entry.ref_id) == ("reservation", reservation.id)
    stored = harness.store.reservations[reservation.id]
    assert (stored.status, stored.committed_amount, stored.settled_at) == ("committed", 25, harness.clock.now())


async def test_commit_of_zero_releases_everything_and_charges_nothing(harness: Harness) -> None:
    await harness.grant(100)
    reservation = await harness.reserve(60)

    result = await harness.service.commit(harness.session, reservation.id, 0, "commit:zero")

    assert (result.charged, result.released, result.allocations) == (0, 60, ())
    assert harness.wallet() == (100, 0)
    assert harness.ledger()[-1] == ("commit", 0, -60)


async def test_commit_above_the_reservation_is_rejected_and_changes_nothing(harness: Harness) -> None:
    await harness.grant(100)
    reservation = await harness.reserve(20)
    before = (list(harness.store.ledger), dict(harness.store.wallets), dict(harness.store.lots))

    with pytest.raises(CommitExceedsReservationError) as raised:
        await harness.service.commit(harness.session, reservation.id, 21, "commit:over")

    assert (raised.value.status_code, raised.value.code) == (422, "commit_exceeds_reservation")
    assert (harness.store.ledger, harness.store.wallets, harness.store.lots) == before
    assert harness.store.reservations[reservation.id].status == "active"


async def test_commit_rejects_negative_amounts(harness: Harness) -> None:
    await harness.grant(10)
    reservation = await harness.reserve(5)

    with pytest.raises(InvalidCreditAmountError):
        await harness.service.commit(harness.session, reservation.id, -1, "commit:negative")


async def test_commit_replay_returns_the_original_result_and_changes_nothing(harness: Harness) -> None:
    await harness.grant(100)
    reservation = await harness.reserve(60)
    first = await harness.service.commit(harness.session, reservation.id, 25, "commit:once")
    before = (list(harness.store.ledger), dict(harness.store.wallets), dict(harness.store.lots))

    again = await harness.service.commit(harness.session, reservation.id, 25, "commit:once")

    assert again == first
    assert (harness.store.ledger, harness.store.wallets, harness.store.lots) == before


async def test_commit_of_a_settled_reservation_under_a_new_key_conflicts(harness: Harness) -> None:
    await harness.grant(100)
    reservation = await harness.reserve(60)
    await harness.service.commit(harness.session, reservation.id, 25, "commit:first")

    with pytest.raises(ReservationNotActiveError) as raised:
        await harness.service.commit(harness.session, reservation.id, 25, "commit:second")

    assert (raised.value.status_code, raised.value.code) == (409, "reservation_not_active")


async def test_commit_of_an_unknown_reservation_is_not_found(harness: Harness) -> None:
    with pytest.raises(ReservationNotFoundError) as raised:
        await harness.service.commit(harness.session, new_id(), 1, "commit:unknown")

    assert raised.value.status_code == 404


async def test_commit_reusing_a_release_key_conflicts(harness: Harness) -> None:
    await harness.grant(100)
    first = await harness.reserve(10)
    second = await harness.reserve(10)
    await harness.service.release(harness.session, first.id, "settle:1")

    with pytest.raises(IdempotencyKeyConflictError):
        await harness.service.commit(harness.session, second.id, 5, "settle:1")


async def test_release_returns_every_held_credit(harness: Harness) -> None:
    await harness.grant(100)
    reservation = await harness.reserve(60)

    result = await harness.service.release(harness.session, reservation.id, "release:one")

    assert (result.released, result.reserved_after) == (60, 0)
    assert harness.wallet() == (100, 0)
    assert harness.ledger()[-1] == ("release", 0, -60)
    assert harness.store.ledger[-1].metadata == {"cause": "release"}
    stored = harness.store.reservations[reservation.id]
    assert (stored.status, stored.settled_at) == ("released", harness.clock.now())


async def test_release_replay_returns_the_original_and_changes_nothing(harness: Harness) -> None:
    await harness.grant(100)
    reservation = await harness.reserve(60)
    first = await harness.service.release(harness.session, reservation.id, "release:once")
    before = (list(harness.store.ledger), dict(harness.store.wallets))

    again = await harness.service.release(harness.session, reservation.id, "release:once")

    assert again == first
    assert (harness.store.ledger, harness.store.wallets) == before


async def test_release_of_a_settled_or_unknown_reservation_fails(harness: Harness) -> None:
    await harness.grant(100)
    reservation = await harness.reserve(60)
    await harness.service.release(harness.session, reservation.id, "release:first")

    with pytest.raises(ReservationNotActiveError):
        await harness.service.release(harness.session, reservation.id, "release:second")
    with pytest.raises(ReservationNotFoundError):
        await harness.service.release(harness.session, new_id(), "release:unknown")


async def test_stale_reservations_are_released_with_status_expired_and_cause_ttl(harness: Harness) -> None:
    await harness.grant(100)
    reservation = await harness.reserve(60, ttl=timedelta(minutes=10))

    assert await harness.service.release_stale(harness.session, reservation.id) is None
    assert await harness.service.stale_reservation_ids(harness.session, None, 10) == []

    harness.clock.advance(timedelta(minutes=10))
    assert await harness.service.stale_reservation_ids(harness.session, None, 10) == [reservation.id]
    result = await harness.service.release_stale(harness.session, reservation.id)

    assert result is not None
    assert (result.released, result.reserved_after) == (60, 0)
    entry = harness.store.ledger[-1]
    assert (entry.reason, entry.delta, entry.reserved_delta) == ("release", 0, -60)
    assert entry.metadata == {"cause": "ttl"}
    assert harness.store.reservations[reservation.id].status == "expired"
    assert await harness.service.stale_reservation_ids(harness.session, None, 10) == []


async def test_stale_release_is_idempotent_and_skips_reservations_settled_meanwhile(harness: Harness) -> None:
    await harness.grant(100)
    reservation = await harness.reserve(60, ttl=timedelta(minutes=1))
    other = await harness.reserve(10, ttl=timedelta(minutes=1))
    harness.clock.advance(timedelta(minutes=2))
    await harness.service.commit(harness.session, other.id, 10, "commit:other")

    first = await harness.service.release_stale(harness.session, reservation.id)
    again = await harness.service.release_stale(harness.session, reservation.id)
    skipped = await harness.service.release_stale(harness.session, other.id)
    unknown = await harness.service.release_stale(harness.session, new_id())

    assert first is not None
    assert again == first
    assert skipped is None
    assert unknown is None
    assert [row[0] for row in harness.ledger()].count("release") == 1


async def test_stale_reservation_listing_is_keyset_paginated(harness: Harness) -> None:
    await harness.grant(1_000)
    ids = sorted([(await harness.reserve(1, ttl=timedelta(minutes=1))).id for _ in range(5)])
    harness.clock.advance(timedelta(minutes=2))

    first = await harness.service.stale_reservation_ids(harness.session, None, 2)
    second = await harness.service.stale_reservation_ids(harness.session, first[-1], 2)
    third = await harness.service.stale_reservation_ids(harness.session, second[-1], 2)

    assert first + second + third == ids
    assert isinstance(first[0], UUID)
