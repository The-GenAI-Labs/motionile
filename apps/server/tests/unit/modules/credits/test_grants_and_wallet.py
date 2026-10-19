from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.settings import make_settings
from tests.unit.modules.credits.conftest import Harness

from motionile.core.ids import new_id
from motionile.modules.credits import (
    CreditRef,
    CreditsService,
    CreditUserNotFoundError,
    DuplicateLotReferenceError,
    GrantCommand,
    IdempotencyKeyConflictError,
    InvalidCreditAmountError,
    InvalidCreditReferenceError,
    InvalidIdempotencyKeyError,
)
from motionile.modules.credits.domain import LotSource


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        ("purchase", "purchase"),
        ("subscription", "subscription_grant"),
        ("promo", "promo_grant"),
        ("admin", "admin_adjust"),
    ],
)
async def test_grant_creates_a_lot_and_one_ledger_row_per_source(
    harness: Harness, source: LotSource, reason: str
) -> None:
    result = await harness.grant(120, source=source, expires_in=timedelta(days=30))

    lot = harness.store.lots[result.lot_id]
    assert (lot.amount, lot.remaining, lot.source) == (120, 120, source)
    assert lot.expires_at == harness.clock.now() + timedelta(days=30)
    assert harness.ledger() == [(reason, 120, 0)]
    assert harness.wallet() == (120, 0)
    assert harness.store.wallets[harness.user_id].version == 1
    assert result.balance_after == 120


async def test_grant_records_the_payment_reference_on_lot_and_ledger(harness: Harness, session: AsyncSession) -> None:
    payment = new_id()

    result = await harness.service.grant(
        session,
        GrantCommand(
            user_id=harness.user_id,
            amount=50,
            source="purchase",
            key="payment:1",
            ref=CreditRef("payment", payment),
        ),
    )

    lot = harness.store.lots[result.lot_id]
    entry = harness.store.ledger[0]
    assert (lot.ref_type, lot.ref_id) == ("payment", payment)
    assert (entry.ref_type, entry.ref_id, entry.idempotency_key) == ("payment", payment, "payment:1")
    assert entry.metadata["lotId"] == str(lot.id)


async def test_grant_without_reference_leaves_both_reference_columns_empty(
    harness: Harness, session: AsyncSession
) -> None:
    result = await harness.service.grant(
        session, GrantCommand(user_id=harness.user_id, amount=5, source="promo", key="promo:free")
    )

    lot = harness.store.lots[result.lot_id]
    assert (lot.ref_type, lot.ref_id, harness.store.ledger[0].ref_id) == (None, None, None)


async def test_grant_replay_returns_the_original_and_changes_nothing(harness: Harness) -> None:
    payment = new_id()
    first = await harness.grant(80, expires_in=timedelta(days=3), key="payment:replayed", payment_id=payment)
    before = (dict(harness.store.lots), list(harness.store.ledger), dict(harness.store.wallets))

    again = await harness.grant(80, expires_in=timedelta(days=9), key="payment:replayed", payment_id=payment)

    assert again == first
    assert (harness.store.lots, harness.store.ledger, harness.store.wallets) == before


@pytest.mark.parametrize("amount", [0, -5])
async def test_grant_rejects_non_positive_amounts(harness: Harness, amount: int) -> None:
    with pytest.raises(InvalidCreditAmountError) as raised:
        await harness.grant(amount)

    assert raised.value.status_code == 422
    assert raised.value.code == "invalid_credit_amount"
    assert harness.store.ledger == []


async def test_grant_rejects_references_a_lot_cannot_carry(harness: Harness, session: AsyncSession) -> None:
    with pytest.raises(InvalidCreditReferenceError):
        await harness.service.grant(
            session,
            GrantCommand(
                user_id=harness.user_id, amount=5, source="purchase", key="k", ref=CreditRef("refund", new_id())
            ),
        )


async def test_grant_rejects_unusable_idempotency_keys(harness: Harness) -> None:
    with pytest.raises(InvalidIdempotencyKeyError):
        await harness.grant(5, key="")
    with pytest.raises(InvalidIdempotencyKeyError):
        await harness.grant(5, key="x" * 201)


async def test_one_payment_cannot_create_two_lots_under_different_keys(harness: Harness, session: AsyncSession) -> None:
    payment = CreditRef("payment", new_id())
    command = GrantCommand(user_id=harness.user_id, amount=10, source="purchase", key="a", ref=payment)
    await harness.service.grant(session, command)

    with pytest.raises(DuplicateLotReferenceError) as raised:
        await harness.service.grant(session, replace(command, key="b"))

    assert raised.value.status_code == 409


async def test_a_key_cannot_be_reused_for_another_user_or_operation(harness: Harness) -> None:
    await harness.grant(10, key="shared")
    await harness.reserve(5, key="shared-reserve")

    with pytest.raises(IdempotencyKeyConflictError):
        await harness.grant(10, user_id=new_id(), key="shared")
    with pytest.raises(IdempotencyKeyConflictError):
        await harness.grant(10, key="shared-reserve")
    with pytest.raises(IdempotencyKeyConflictError):
        await harness.grant(11, key="shared")


async def test_grant_for_an_unknown_user_is_not_found(session: AsyncSession) -> None:
    harness = Harness(session)
    harness.store.known_users = set()
    harness.service = CreditsService(
        harness.clock, make_settings().billing, store_factory=harness.store, audit=harness.audit
    )

    with pytest.raises(CreditUserNotFoundError) as raised:
        await harness.grant(10)

    assert raised.value.status_code == 404


async def test_wallet_without_a_row_reads_as_zero_and_is_not_created(harness: Harness, session: AsyncSession) -> None:
    view = await harness.service.wallet(session, harness.user_id)

    assert (view.balance, view.reserved, view.available, view.expiring_soon) == (0, 0, 0, ())
    assert harness.store.wallets == {}


async def test_wallet_available_is_balance_minus_reserved(harness: Harness, session: AsyncSession) -> None:
    await harness.grant(100)
    await harness.reserve(30)

    view = await harness.service.wallet(session, harness.user_id)

    assert (view.balance, view.reserved, view.available) == (100, 30, 70)


async def test_wallet_available_excludes_expired_credits_nobody_holds(harness: Harness, session: AsyncSession) -> None:
    await harness.grant(40, expires_in=timedelta(days=1))
    await harness.grant(60)
    harness.clock.advance(timedelta(days=2))

    view = await harness.service.wallet(session, harness.user_id)

    assert (view.balance, view.available) == (100, 60)
    assert harness.wallet() == (100, 0)


async def test_wallet_keeps_expired_credits_that_a_reservation_holds(harness: Harness, session: AsyncSession) -> None:
    await harness.grant(40, expires_in=timedelta(days=1))
    await harness.reserve(40, ttl=timedelta(days=5))
    harness.clock.advance(timedelta(days=2))

    view = await harness.service.wallet(session, harness.user_id)

    assert (view.balance, view.reserved, view.available) == (40, 40, 0)


async def test_wallet_lists_only_lots_expiring_within_the_reminder_window(
    harness: Harness, session: AsyncSession
) -> None:
    await harness.grant(10, expires_in=timedelta(days=3), source="subscription")
    await harness.grant(20, expires_in=timedelta(days=20))
    await harness.grant(30)
    soon = await harness.grant(5, expires_in=timedelta(days=7))
    await harness.grant(7, expires_in=timedelta(days=-1))

    view = await harness.service.wallet(session, harness.user_id)

    assert [(lot.source, lot.remaining) for lot in view.expiring_soon] == [("subscription", 10), ("purchase", 5)]
    assert harness.store.lots[soon.lot_id].expires_at == view.expiring_soon[1].expires_at


async def test_wallet_never_creates_a_row_for_other_users(harness: Harness, session: AsyncSession) -> None:
    await harness.grant(10)
    other = new_id()

    view = await harness.service.wallet(session, other)

    assert view.balance == 0
    assert other not in harness.store.wallets
