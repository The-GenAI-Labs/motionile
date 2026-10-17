from datetime import datetime, timedelta
from typing import TypedDict, Unpack
from uuid import UUID

import pytest
from tests.unit.modules.credits.conftest import Harness

from motionile.core.ids import new_id
from motionile.modules.audit import ActorType
from motionile.modules.credits import (
    AdjustCommand,
    AdjustmentExceedsAvailableError,
    ClawbackCommand,
    CreditRef,
    CreditUserNotFoundError,
    IdempotencyKeyConflictError,
    InvalidAdjustmentReasonError,
    InvalidCreditAmountError,
    InvalidCreditExpiryError,
    InvalidCreditReferenceError,
    LotNotFoundError,
)


def clawback_command(lot_id: UUID, amount: int, key: str, refund: UUID | None = None) -> ClawbackCommand:
    return ClawbackCommand(
        lot_id=lot_id, amount=amount, reason="refund of pack", ref=CreditRef("refund", refund or new_id()), key=key
    )


class AdjustOptions(TypedDict, total=False):
    reason: str
    actor_id: UUID
    expires_at: datetime


def adjust_command(harness: Harness, delta: int, key: str, **options: Unpack[AdjustOptions]) -> AdjustCommand:
    return AdjustCommand(
        user_id=harness.user_id,
        delta=delta,
        reason=options.get("reason", "goodwill"),
        actor_id=options.get("actor_id") or new_id(),
        key=key,
        expires_at=options.get("expires_at"),
    )


async def test_clawback_takes_the_whole_request_when_the_lot_and_wallet_allow_it(harness: Harness) -> None:
    lot = await harness.grant(100)
    refund = new_id()

    result = await harness.service.clawback(harness.session, clawback_command(lot.lot_id, 60, "refund:1", refund))

    assert (result.requested, result.clawed_back, result.balance_after) == (60, 60, 40)
    assert harness.lot_remaining(lot.lot_id) == 40
    assert harness.wallet() == (40, 0)
    entry = harness.store.ledger[-1]
    assert (entry.reason, entry.delta, entry.reserved_delta) == ("refund_clawback", -60, 0)
    assert (entry.ref_type, entry.ref_id) == ("refund", refund)
    assert entry.metadata == {"lotId": str(lot.lot_id), "requested": 60, "reason": "refund of pack"}


async def test_clawback_is_capped_by_what_remains_in_the_lot(harness: Harness) -> None:
    lot = await harness.grant(100)
    other = await harness.grant(500)
    reservation = await harness.reserve(70)
    await harness.service.commit(harness.session, reservation.id, 70, "commit:spend")

    result = await harness.service.clawback(harness.session, clawback_command(lot.lot_id, 100, "refund:cap"))

    assert result.clawed_back == 30
    assert harness.lot_remaining(lot.lot_id) == 0
    assert harness.lot_remaining(other.lot_id) == 500


async def test_clawback_is_capped_by_credits_held_by_reservations(harness: Harness) -> None:
    lot = await harness.grant(100)
    await harness.reserve(80)

    result = await harness.service.clawback(harness.session, clawback_command(lot.lot_id, 100, "refund:held"))

    assert result.clawed_back == 20
    assert harness.wallet() == (80, 80)
    assert harness.lot_remaining(lot.lot_id) == 80


async def test_clawback_with_nothing_to_take_writes_no_ledger_row(harness: Harness) -> None:
    lot = await harness.grant(100)
    await harness.reserve(100)
    rows = len(harness.store.ledger)

    result = await harness.service.clawback(harness.session, clawback_command(lot.lot_id, 50, "refund:none"))

    assert (result.requested, result.clawed_back, result.balance_after) == (50, 0, 100)
    assert len(harness.store.ledger) == rows
    assert harness.lot_remaining(lot.lot_id) == 100


async def test_clawback_replay_returns_the_original_and_changes_nothing(harness: Harness) -> None:
    lot = await harness.grant(100)
    refund = new_id()
    first = await harness.service.clawback(harness.session, clawback_command(lot.lot_id, 60, "refund:r", refund))
    before = (list(harness.store.ledger), dict(harness.store.lots), dict(harness.store.wallets))

    again = await harness.service.clawback(harness.session, clawback_command(lot.lot_id, 60, "refund:r", refund))

    assert again == first
    assert (harness.store.ledger, harness.store.lots, harness.store.wallets) == before


async def test_clawback_validates_amount_reference_and_reason(harness: Harness) -> None:
    lot = await harness.grant(100)

    with pytest.raises(InvalidCreditAmountError):
        await harness.service.clawback(harness.session, clawback_command(lot.lot_id, 0, "refund:zero"))
    with pytest.raises(InvalidCreditReferenceError):
        await harness.service.clawback(
            harness.session,
            ClawbackCommand(lot_id=lot.lot_id, amount=5, reason="x", ref=CreditRef("payment", new_id()), key="k"),
        )
    with pytest.raises(InvalidAdjustmentReasonError):
        await harness.service.clawback(
            harness.session,
            ClawbackCommand(lot_id=lot.lot_id, amount=5, reason="  ", ref=CreditRef("refund", new_id()), key="k"),
        )


async def test_clawback_of_an_unknown_lot_is_not_found(harness: Harness) -> None:
    with pytest.raises(LotNotFoundError) as raised:
        await harness.service.clawback(harness.session, clawback_command(new_id(), 5, "refund:unknown"))

    assert raised.value.status_code == 404


async def test_clawback_never_takes_credits_that_already_expired(harness: Harness) -> None:
    lot = await harness.grant(100, expires_in=timedelta(days=1))
    other = await harness.grant(50)
    harness.clock.advance(timedelta(days=2))

    result = await harness.service.clawback(harness.session, clawback_command(lot.lot_id, 100, "refund:expired"))

    assert result.clawed_back == 0
    assert harness.lot_remaining(lot.lot_id) == 0
    assert harness.lot_remaining(other.lot_id) == 50
    assert harness.ledger()[-1] == ("expiry", -100, 0)


async def test_positive_adjustment_creates_an_admin_lot_with_an_action_reference(harness: Harness) -> None:
    actor = new_id()

    result = await harness.service.adjust(
        harness.session, adjust_command(harness, 75, "adjust:1", actor_id=actor, reason="  welcome bonus  ")
    )

    assert result.lot_id is not None
    lot = harness.store.lots[result.lot_id]
    assert (lot.source, lot.amount, lot.remaining, lot.expires_at) == ("admin", 75, 75, None)
    assert (lot.ref_type, lot.ref_id) == ("admin", result.action_id)
    entry = harness.store.ledger[-1]
    assert (entry.reason, entry.delta, entry.reserved_delta) == ("admin_adjust", 75, 0)
    assert (entry.ref_type, entry.ref_id) == ("admin", result.action_id)
    assert entry.metadata["actorId"] == str(actor)
    assert entry.metadata["reason"] == "welcome bonus"
    assert harness.wallet() == (75, 0)


async def test_positive_adjustment_may_expire(harness: Harness) -> None:
    expiry = harness.clock.now() + timedelta(days=30)

    result = await harness.service.adjust(harness.session, adjust_command(harness, 10, "adjust:exp", expires_at=expiry))

    assert result.lot_id is not None
    assert harness.store.lots[result.lot_id].expires_at == expiry


async def test_negative_adjustment_consumes_lots_in_expiry_order(harness: Harness) -> None:
    forever = await harness.grant(50)
    soon = await harness.grant(30, expires_in=timedelta(days=2))

    result = await harness.service.adjust(harness.session, adjust_command(harness, -40, "adjust:take"))

    assert [(item.lot_id, item.amount) for item in result.allocations] == [(soon.lot_id, 30), (forever.lot_id, 10)]
    assert result.lot_id is None
    assert harness.wallet() == (40, 0)
    entry = harness.store.ledger[-1]
    assert (entry.reason, entry.delta, entry.reserved_delta) == ("admin_adjust", -40, 0)
    assert entry.metadata["allocations"] == [
        {"lotId": str(soon.lot_id), "amount": 30},
        {"lotId": str(forever.lot_id), "amount": 10},
    ]


async def test_negative_adjustment_cannot_exceed_available_credits(harness: Harness) -> None:
    await harness.grant(100)
    await harness.reserve(70)

    with pytest.raises(AdjustmentExceedsAvailableError) as raised:
        await harness.service.adjust(harness.session, adjust_command(harness, -31, "adjust:over"))

    assert (raised.value.status_code, raised.value.code) == (409, "adjustment_exceeds_available")
    assert harness.wallet() == (100, 70)
    await harness.service.adjust(harness.session, adjust_command(harness, -30, "adjust:exact"))
    assert harness.wallet() == (70, 70)


async def test_negative_adjustment_without_a_wallet_conflicts(harness: Harness) -> None:
    with pytest.raises(AdjustmentExceedsAvailableError):
        await harness.service.adjust(harness.session, adjust_command(harness, -1, "adjust:empty"))

    assert harness.store.wallets == {}


async def test_adjustment_cannot_spend_credits_that_have_expired(harness: Harness) -> None:
    await harness.grant(40, expires_in=timedelta(days=1))
    await harness.grant(10)
    harness.clock.advance(timedelta(days=2))

    with pytest.raises(AdjustmentExceedsAvailableError):
        await harness.service.adjust(harness.session, adjust_command(harness, -11, "adjust:stale"))
    await harness.service.adjust(harness.session, adjust_command(harness, -10, "adjust:fresh"))

    assert harness.wallet() == (0, 0)


async def test_zero_adjustment_is_rejected(harness: Harness) -> None:
    with pytest.raises(InvalidCreditAmountError):
        await harness.service.adjust(harness.session, adjust_command(harness, 0, "adjust:zero"))


@pytest.mark.parametrize("reason", ["", "   ", "x" * 501])
async def test_adjustment_reason_must_be_one_to_five_hundred_characters(harness: Harness, reason: str) -> None:
    with pytest.raises(InvalidAdjustmentReasonError):
        await harness.service.adjust(harness.session, adjust_command(harness, 5, "adjust:reason", reason=reason))


async def test_adjustment_accepts_the_longest_reason(harness: Harness) -> None:
    await harness.service.adjust(harness.session, adjust_command(harness, 5, "adjust:long", reason="x" * 500))

    assert harness.wallet() == (5, 0)


async def test_adjustment_expiry_must_be_in_the_future_and_only_for_grants(harness: Harness) -> None:
    with pytest.raises(InvalidCreditExpiryError):
        await harness.service.adjust(
            harness.session, adjust_command(harness, 5, "adjust:past", expires_at=harness.clock.now())
        )
    await harness.grant(10)
    with pytest.raises(InvalidCreditExpiryError):
        await harness.service.adjust(
            harness.session,
            adjust_command(harness, -5, "adjust:deduct", expires_at=harness.clock.now() + timedelta(days=1)),
        )


async def test_adjustment_replay_returns_the_original_and_audits_once(harness: Harness) -> None:
    command = adjust_command(harness, 25, "adjust:replay")
    first = await harness.service.adjust(harness.session, command)
    before = (list(harness.store.ledger), dict(harness.store.lots), dict(harness.store.wallets))

    again = await harness.service.adjust(harness.session, command)

    assert again == first
    assert (harness.store.ledger, harness.store.lots, harness.store.wallets) == before
    assert len(harness.audit.events) == 1


async def test_adjustment_writes_an_audit_entry_for_the_acting_admin(harness: Harness) -> None:
    command = adjust_command(harness, 25, "adjust:audit", reason="compensation")

    result = await harness.service.adjust(harness.session, command)

    event = harness.audit.events[0]
    assert event.action == "credits.adjusted"
    assert event.actor_type is ActorType.ADMIN
    assert event.actor_user_id == command.actor_id
    assert (event.target_type, event.target_id) == ("user", str(harness.user_id))
    assert event.metadata == {
        "delta": 25,
        "reason": "compensation",
        "actionId": str(result.action_id),
        "ledgerKey": "adjust:audit",
    }


async def test_failed_adjustment_writes_no_audit_entry(harness: Harness) -> None:
    with pytest.raises(AdjustmentExceedsAvailableError):
        await harness.service.adjust(harness.session, adjust_command(harness, -5, "adjust:fail"))

    assert harness.audit.events == []


async def test_adjustment_key_reuse_with_another_delta_conflicts(harness: Harness) -> None:
    await harness.service.adjust(harness.session, adjust_command(harness, 25, "adjust:key"))

    with pytest.raises(IdempotencyKeyConflictError):
        await harness.service.adjust(harness.session, adjust_command(harness, 26, "adjust:key"))


async def test_positive_adjustment_for_an_unknown_user_is_not_found(harness: Harness) -> None:
    harness.store.known_users = set()

    with pytest.raises(CreditUserNotFoundError):
        await harness.service.adjust(harness.session, adjust_command(harness, 5, "adjust:ghost"))
