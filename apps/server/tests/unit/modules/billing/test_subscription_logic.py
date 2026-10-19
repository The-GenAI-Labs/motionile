from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import product
from uuid import UUID

import pytest

from motionile.core.ids import new_id
from motionile.modules.billing.exceptions import SubscriptionPeriodUnknownError
from motionile.modules.billing.razorpay.models import RazorpayPayment, RazorpaySubscription
from motionile.modules.billing.records import ProductRecord, SubscriptionRecord
from motionile.modules.billing.services.subscription_logic import (
    Move,
    changed_values,
    charge_matches_product,
    decide_move,
    grant_expiry,
    is_stale,
    merged_period,
    newest_event_time,
    plan_cancellation,
    plan_switch,
    plan_sync,
)
from motionile.modules.billing.states import SUBSCRIPTION_MACHINE, SubscriptionStatus

NOW = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
MONTH = timedelta(days=30)


def epoch(moment: datetime) -> int:
    return int(moment.timestamp())


def local(status: SubscriptionStatus = SubscriptionStatus.ACTIVE, **values: object) -> SubscriptionRecord:
    base = SubscriptionRecord(
        id=new_id(),
        user_id=new_id(),
        product_id=new_id(),
        pending_product_id=None,
        razorpay_subscription_id="sub_1",
        status=status,
        total_count=120,
        paid_count=1,
        current_period_start=NOW,
        current_period_end=NOW + MONTH,
        next_charge_at=NOW + MONTH,
        cancel_at_period_end=False,
        cancelled_at=None,
        ended_at=None,
        last_event_at=NOW,
        created_at=NOW,
    )
    return replace(base, **values)


def remote(status: str = "active", **values: object) -> RazorpaySubscription:
    document: dict[str, object] = {
        "id": "sub_1",
        "plan_id": "plan_1",
        "status": status,
        "current_start": epoch(NOW),
        "current_end": epoch(NOW + MONTH),
        "charge_at": epoch(NOW + MONTH),
        "total_count": 120,
        "paid_count": 1,
        "created_at": epoch(NOW),
        **values,
    }
    return RazorpaySubscription.model_validate(document)


def plan(product_id: UUID | None = None, plan_id: str = "plan_1") -> ProductRecord:
    return ProductRecord(
        id=product_id or new_id(),
        code="pro",
        kind="subscription",
        plan_key="pro",
        name="Pro",
        description=None,
        price_paise=99_900,
        currency="INR",
        interval="month",
        credits_granted=500,
        razorpay_plan_id=plan_id,
        is_active=True,
        is_sample=False,
        sort_order=1,
        features=(),
        version=1,
    )


def payment(amount: int = 99_900, currency: str = "INR") -> RazorpayPayment:
    return RazorpayPayment.model_validate(
        {
            "id": "pay_1",
            "amount": amount,
            "currency": currency,
            "status": "captured",
            "captured": True,
            "created_at": epoch(NOW),
        }
    )


@pytest.mark.parametrize(
    ("event_at", "last_at", "stale"),
    [
        (NOW - timedelta(seconds=1), NOW, True),
        (NOW, NOW, False),
        (NOW + timedelta(seconds=1), NOW, False),
        (None, NOW, False),
        (NOW, None, False),
        (None, None, False),
    ],
)
def test_only_an_event_older_than_the_last_applied_one_is_stale(
    event_at: datetime | None, last_at: datetime | None, stale: bool
) -> None:
    assert is_stale(event_at, last_at) is stale


def test_the_newest_event_time_ignores_missing_values() -> None:
    assert newest_event_time(None, None) is None
    assert newest_event_time(NOW, None) == NOW
    assert newest_event_time(None, NOW) == NOW
    assert newest_event_time(NOW, NOW + MONTH) == NOW + MONTH


@pytest.mark.parametrize(("current", "target"), list(product(SubscriptionStatus, SubscriptionStatus)))
def test_a_move_is_applied_only_when_the_diagram_allows_it_and_repeats_are_no_ops(
    current: SubscriptionStatus, target: SubscriptionStatus
) -> None:
    expected = (
        Move.APPLY
        if SUBSCRIPTION_MACHINE.allows(current, target)
        else (Move.NOOP if current == target else Move.REJECT)
    )

    assert decide_move(current, target) is expected


def test_period_fields_only_move_forward_and_the_paid_count_never_drops() -> None:
    subscription = local(paid_count=3)
    later = remote(current_start=epoch(NOW + MONTH), current_end=epoch(NOW + 2 * MONTH), paid_count=2)
    earlier = remote(current_start=epoch(NOW - MONTH), current_end=epoch(NOW), paid_count=1)

    forward = merged_period(subscription, later)
    backward = merged_period(subscription, earlier)

    assert forward["current_period_end"] == NOW + 2 * MONTH
    assert forward["current_period_start"] == NOW + MONTH
    assert forward["next_charge_at"] == NOW + MONTH
    assert forward["paid_count"] == 3
    assert backward == {"paid_count": 3}


def test_a_remote_without_a_period_changes_only_the_paid_count() -> None:
    assert merged_period(local(), remote(current_start=None, current_end=None, charge_at=None, paid_count=4)) == {
        "paid_count": 4
    }


def test_a_plan_switch_names_the_new_product_and_clears_a_matching_pending_one() -> None:
    current = plan()
    target = plan()
    subscription = local(product_id=current.id, pending_product_id=target.id)

    assert plan_switch(subscription, target) == {"product_id": target.id, "pending_product_id": None}
    assert plan_switch(replace(subscription, pending_product_id=None), target) == {"product_id": target.id}
    assert plan_switch(subscription, current) == {}
    assert plan_switch(subscription, None) == {}


def test_the_pending_product_stays_when_a_different_plan_takes_over() -> None:
    pending = plan()
    other = plan()
    subscription = local(pending_product_id=pending.id)

    assert plan_switch(subscription, other) == {"product_id": other.id}


@pytest.mark.parametrize(
    ("status", "period_end", "end_now"),
    [
        (SubscriptionStatus.CREATED, NOW + MONTH, True),
        (SubscriptionStatus.AUTHENTICATED, NOW + MONTH, True),
        (SubscriptionStatus.ACTIVE, None, True),
        (SubscriptionStatus.ACTIVE, NOW - timedelta(seconds=1), True),
        (SubscriptionStatus.ACTIVE, NOW, True),
        (SubscriptionStatus.ACTIVE, NOW + timedelta(seconds=1), False),
        (SubscriptionStatus.PENDING, NOW + MONTH, False),
        (SubscriptionStatus.HALTED, NOW + MONTH, False),
        (SubscriptionStatus.PAUSED, NOW + MONTH, False),
    ],
)
def test_a_cancellation_ends_the_subscription_only_when_no_paid_period_is_left(
    status: SubscriptionStatus, period_end: datetime | None, end_now: bool
) -> None:
    assert plan_cancellation(status, period_end, NOW).end_now is end_now


def test_credits_expire_with_the_period_unless_they_roll_over() -> None:
    assert grant_expiry(NOW + MONTH, rollover=False) == NOW + MONTH
    assert grant_expiry(NOW + MONTH, rollover=True) is None
    assert grant_expiry(None, rollover=True) is None
    with pytest.raises(SubscriptionPeriodUnknownError):
        grant_expiry(None, rollover=False)


@pytest.mark.parametrize(
    ("amount", "currency", "matches"),
    [(99_900, "INR", True), (99_899, "INR", False), (99_901, "INR", False), (99_900, "USD", False)],
)
def test_a_charge_must_match_the_product_price_and_currency(amount: int, currency: str, matches: bool) -> None:
    assert charge_matches_product(plan(), payment(amount, currency)) is matches


def test_changed_values_keeps_only_real_differences() -> None:
    subscription = local(paid_count=2)

    assert changed_values(subscription, {"paid_count": 2, "total_count": 120, "cancel_at_period_end": True}) == {
        "cancel_at_period_end": True
    }


def test_a_matching_remote_needs_no_repair() -> None:
    product = plan()

    sync = plan_sync(local(product_id=product.id), remote(), product, NOW)

    assert not sync.changes_anything
    assert not sync.unresolved


def test_a_remote_that_is_further_along_is_walked_through_allowed_states() -> None:
    sync = plan_sync(local(SubscriptionStatus.PENDING), remote("completed", ended_at=epoch(NOW)), None, NOW)

    assert sync.path == (SubscriptionStatus.ACTIVE, SubscriptionStatus.COMPLETED)
    assert sync.values["ended_at"] == NOW
    assert not sync.unresolved


def test_a_local_subscription_that_is_ahead_of_the_remote_is_left_alone() -> None:
    sync = plan_sync(local(SubscriptionStatus.ACTIVE), remote("authenticated"), None, NOW)

    assert sync.path == ()
    assert not sync.unresolved


def test_a_remote_state_that_cannot_be_reached_is_a_mismatch() -> None:
    completed = local(SubscriptionStatus.COMPLETED, ended_at=NOW)

    to_expired = plan_sync(completed, remote("expired"), None, NOW)
    to_cancelled = plan_sync(completed, remote("cancelled"), None, NOW)

    assert to_expired.path == to_cancelled.path == ()
    assert to_expired.unresolved
    assert to_cancelled.unresolved


def test_an_unknown_remote_status_is_unresolved() -> None:
    assert plan_sync(local(), remote("mystery"), None, NOW).unresolved


def test_a_remote_cancellation_ends_the_local_subscription_when_no_paid_period_is_left() -> None:
    expired = remote("cancelled", ended_at=epoch(NOW), current_end=epoch(NOW - timedelta(days=1)))

    sync = plan_sync(local(SubscriptionStatus.ACTIVE, current_period_end=NOW - timedelta(days=1)), expired, None, NOW)

    assert sync.path == (SubscriptionStatus.CANCELLED,)
    assert sync.values["cancel_at_period_end"] is True
    assert sync.values["ended_at"] == NOW


def test_a_remote_cancellation_with_a_paid_period_left_only_marks_the_cancellation() -> None:
    sync = plan_sync(local(SubscriptionStatus.ACTIVE), remote("cancelled", ended_at=epoch(NOW)), None, NOW)

    assert sync.path == ()
    assert sync.values["cancel_at_period_end"] is True
    assert "ended_at" not in sync.values


def test_a_remote_plan_and_counts_are_copied() -> None:
    target = plan()
    subscription = local(product_id=new_id(), pending_product_id=target.id)

    sync = plan_sync(subscription, remote(paid_count=4, total_count=60), target, NOW)

    assert sync.values["product_id"] == target.id
    assert sync.values["pending_product_id"] is None
    assert sync.values["paid_count"] == 4
    assert sync.values["total_count"] == 60
