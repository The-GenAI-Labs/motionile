from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from motionile.modules.billing.razorpay.models import RazorpayPayment, RazorpaySubscription
from motionile.modules.billing.records import ProductRecord, SubscriptionRecord
from motionile.modules.billing.states import (
    ENDED_SUBSCRIPTION_STATUSES,
    SUBSCRIPTION_MACHINE,
    SubscriptionStatus,
)

STALE_EVENT = "stale"
INVALID_TRANSITION = "invalid_transition"
NEVER_CHARGED = frozenset({SubscriptionStatus.CREATED, SubscriptionStatus.AUTHENTICATED})
ACTIVATABLE = NEVER_CHARGED
CHARGE_ACTIVATES = frozenset(
    {
        SubscriptionStatus.CREATED,
        SubscriptionStatus.AUTHENTICATED,
        SubscriptionStatus.PENDING,
        SubscriptionStatus.HALTED,
        SubscriptionStatus.ACTIVE,
    }
)

type Values = dict[str, Any]


class Move(StrEnum):
    APPLY = "apply"
    NOOP = "noop"
    REJECT = "reject"


def is_stale(event_created_at: datetime | None, last_event_at: datetime | None) -> bool:
    return event_created_at is not None and last_event_at is not None and event_created_at < last_event_at


def newest_event_time(last_event_at: datetime | None, event_created_at: datetime | None) -> datetime | None:
    known = [moment for moment in (last_event_at, event_created_at) if moment is not None]
    return max(known, default=None)


def decide_move(current: SubscriptionStatus, target: SubscriptionStatus) -> Move:
    if SUBSCRIPTION_MACHINE.allows(current, target):
        return Move.APPLY
    return Move.NOOP if current == target else Move.REJECT


def merged_period(subscription: SubscriptionRecord, remote: RazorpaySubscription) -> Values:
    values: Values = {"paid_count": max(subscription.paid_count, remote.paid_count)}
    end = remote.current_end_utc
    if end is None or (subscription.current_period_end is not None and end < subscription.current_period_end):
        return values
    start = remote.current_start_utc
    if start is not None and start < end:
        values["current_period_start"] = start
    values["current_period_end"] = end
    values["next_charge_at"] = remote.charge_at_utc
    return values


def plan_switch(subscription: SubscriptionRecord, plan_product: ProductRecord | None) -> Values:
    if plan_product is None or plan_product.id == subscription.product_id:
        return {}
    values: Values = {"product_id": plan_product.id}
    if subscription.pending_product_id == plan_product.id:
        values["pending_product_id"] = None
    return values


def changed_values(subscription: SubscriptionRecord, values: Values) -> Values:
    return {name: value for name, value in values.items() if getattr(subscription, name) != value}


@dataclass(frozen=True)
class CancellationPlan:
    end_now: bool


def plan_cancellation(status: SubscriptionStatus, period_end: datetime | None, now: datetime) -> CancellationPlan:
    no_paid_period = status in NEVER_CHARGED or period_end is None or period_end <= now
    return CancellationPlan(end_now=no_paid_period)


def grant_expiry(period_end: datetime | None, *, rollover: bool) -> datetime | None:
    return None if rollover else period_end


def charge_matches_product(product: ProductRecord, payment: RazorpayPayment) -> bool:
    return payment.amount == product.price_paise and payment.currency == product.currency


def ended_values(ended_at: datetime) -> Values:
    return {"ended_at": ended_at}


@dataclass(frozen=True)
class SyncPlan:
    path: tuple[SubscriptionStatus, ...]
    values: Values
    unresolved: bool

    @property
    def changes_anything(self) -> bool:
        return bool(self.path) or bool(self.values)


def remote_status(remote: RazorpaySubscription) -> SubscriptionStatus | None:
    try:
        return SubscriptionStatus(remote.status)
    except ValueError:
        return None


def plan_sync(
    subscription: SubscriptionRecord,
    remote: RazorpaySubscription,
    plan_product: ProductRecord | None,
    now: datetime,
) -> SyncPlan:
    target = remote_status(remote)
    if target is None:
        return SyncPlan((), {}, unresolved=True)
    values: Values = {**merged_period(subscription, remote), **plan_switch(subscription, plan_product)}
    if remote.total_count != subscription.total_count:
        values["total_count"] = remote.total_count
    path: tuple[SubscriptionStatus, ...] = ()
    unresolved = False
    if target == SubscriptionStatus.CANCELLED:
        path, extra = cancelled_sync(subscription, remote, now)
        values.update(extra)
        unresolved = subscription.status in ENDED_SUBSCRIPTION_STATUSES - {SubscriptionStatus.CANCELLED}
    elif target != subscription.status:
        route = SUBSCRIPTION_MACHINE.path(subscription.status, target)
        behind = SUBSCRIPTION_MACHINE.path(target, subscription.status) is not None
        path = route or ()
        unresolved = route is None and not behind
    if path and path[-1] in ENDED_SUBSCRIPTION_STATUSES:
        values.update(ended_values(remote.ended_at_utc or now))
    return SyncPlan(path, changed_values(subscription, values), unresolved)


def cancelled_sync(
    subscription: SubscriptionRecord, remote: RazorpaySubscription, now: datetime
) -> tuple[tuple[SubscriptionStatus, ...], Values]:
    period_end = remote.current_end_utc or subscription.current_period_end
    values: Values = {"cancel_at_period_end": True}
    if subscription.cancelled_at is None:
        values["cancelled_at"] = remote.ended_at_utc or now
    if subscription.status == SubscriptionStatus.CANCELLED:
        return (), values
    if plan_cancellation(subscription.status, period_end, now).end_now:
        route = SUBSCRIPTION_MACHINE.path(subscription.status, SubscriptionStatus.CANCELLED)
        return route or (), values
    return (), values
