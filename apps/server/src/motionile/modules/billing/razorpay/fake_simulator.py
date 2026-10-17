from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from motionile.core.clock import Clock
from motionile.modules.billing.razorpay.fake_entities import (
    OrderSpec,
    PaymentSpec,
    add_period,
    epoch,
    new_entity_id,
    order_entity,
    payment_entity,
    require,
)
from motionile.modules.billing.razorpay.fake_store import Entity, EntityKind, FakeRazorpayStore
from motionile.modules.billing.razorpay.models import PaymentStatus, RefundStatus, SubscriptionStatus


class FakeRazorpayStateError(Exception):
    pass


class PaymentOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    AUTHORIZED = "authorized"


class SubscriptionEvent(StrEnum):
    ACTIVATED = "activated"
    CHARGED = "charged"
    PENDING = "pending"
    HALTED = "halted"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    PAUSED = "paused"
    RESUMED = "resumed"
    UPDATED = "updated"


class RefundOutcome(StrEnum):
    PROCESSED = "processed"
    FAILED = "failed"


@dataclass(frozen=True)
class OrderPayment:
    order: Entity
    payment: Entity


@dataclass(frozen=True)
class SubscriptionAuthorization:
    subscription: Entity
    payment: Entity


@dataclass(frozen=True)
class SubscriptionTransition:
    subscription: Entity
    payment: Entity | None


@dataclass(frozen=True)
class RefundSettlement:
    refund: Entity
    payment: Entity


PAYMENT_STATUS_BY_OUTCOME = {
    PaymentOutcome.SUCCESS: PaymentStatus.CAPTURED,
    PaymentOutcome.FAILURE: PaymentStatus.FAILED,
    PaymentOutcome.AUTHORIZED: PaymentStatus.AUTHORIZED,
}
TERMINAL_STATUSES = frozenset({SubscriptionStatus.CANCELLED, SubscriptionStatus.COMPLETED, SubscriptionStatus.EXPIRED})
CHARGEABLE = frozenset({SubscriptionStatus.AUTHENTICATED, SubscriptionStatus.ACTIVE, SubscriptionStatus.PENDING})


class FakeRazorpaySimulator:
    def __init__(self, store: FakeRazorpayStore, clock: Clock) -> None:
        self.store = store
        self.clock = clock

    async def _record_payment(self, payment: Entity) -> None:
        await self.store.put(EntityKind.PAYMENT, payment["id"], payment)
        await self.store.append("payments", "all", payment["id"])
        if payment["order_id"]:
            await self.store.append("order_payments", payment["order_id"], payment["id"])

    async def pay_order(
        self,
        order_id: str,
        outcome: PaymentOutcome,
        *,
        amount: int | None = None,
        currency: str | None = None,
        method: str = "card",
    ) -> OrderPayment:
        order = await require(self.store, EntityKind.ORDER, order_id)
        if order["status"] == "paid" and outcome is not PaymentOutcome.FAILURE:
            raise FakeRazorpayStateError("the order has already been paid")
        status = PAYMENT_STATUS_BY_OUTCOME[outcome]
        payment = payment_entity(
            await new_entity_id(self.store, "pay"),
            self.clock.now(),
            PaymentSpec(
                amount=order["amount"] if amount is None else amount,
                currency=currency or order["currency"],
                status=status.value,
                method=method,
                order_id=order_id,
                notes=order["notes"],
            ),
        )
        order["attempts"] += 1
        if status is PaymentStatus.CAPTURED:
            order["amount_paid"] += payment["amount"]
            order["amount_due"] = max(order["amount"] - order["amount_paid"], 0)
            order["status"] = "paid" if order["amount_paid"] >= order["amount"] else "attempted"
        elif order["status"] != "paid":
            order["status"] = "attempted"
        await self._record_payment(payment)
        await self.store.put(EntityKind.ORDER, order_id, order)
        return OrderPayment(order=order, payment=payment)

    async def _subscription_payment(self, subscription: Entity, plan: Entity) -> Entity:
        now = self.clock.now()
        item = plan["item"]
        order = order_entity(await new_entity_id(self.store, "order"), now, OrderSpec(item["amount"], item["currency"]))
        payment = payment_entity(
            await new_entity_id(self.store, "pay"),
            now,
            PaymentSpec(
                amount=item["amount"],
                currency=item["currency"],
                status=PaymentStatus.CAPTURED.value,
                order_id=order["id"],
                invoice_id=await new_entity_id(self.store, "inv"),
                notes=subscription["notes"],
            ),
        )
        order.update(amount_paid=item["amount"], amount_due=0, status="paid", attempts=1)
        await self.store.put(EntityKind.ORDER, order["id"], order)
        await self._record_payment(payment)
        await self.store.append("subscription_payments", subscription["id"], payment["id"])
        return payment

    async def authorize_subscription(self, subscription_id: str) -> SubscriptionAuthorization:
        subscription = await require(self.store, EntityKind.SUBSCRIPTION, subscription_id)
        if subscription["status"] != SubscriptionStatus.CREATED:
            raise FakeRazorpayStateError("only a created subscription can be authorized")
        plan = await require(self.store, EntityKind.PLAN, subscription["plan_id"])
        payment = await self._subscription_payment(subscription, plan)
        subscription["status"] = SubscriptionStatus.AUTHENTICATED.value
        subscription["auth_attempts"] += 1
        await self.store.put(EntityKind.SUBSCRIPTION, subscription_id, subscription)
        return SubscriptionAuthorization(subscription=subscription, payment=payment)

    async def _first_payment(self, subscription_id: str) -> Entity | None:
        members = await self.store.members("subscription_payments", subscription_id)
        return await self.store.get(EntityKind.PAYMENT, members[0]) if members else None

    def _open_period(self, subscription: Entity, plan: Entity, *, continuing: bool) -> None:
        start = (
            subscription["current_end"]
            if continuing and subscription["current_end"] is not None
            else epoch(self.clock.now())
        )
        started = datetime.fromtimestamp(start, UTC)
        subscription["current_start"] = start
        subscription["current_end"] = epoch(add_period(started, plan["period"], plan["interval"]))
        subscription["charge_at"] = subscription["current_end"]
        subscription["status"] = SubscriptionStatus.ACTIVE.value

    @staticmethod
    def _sync_counts(subscription: Entity) -> None:
        subscription["remaining_count"] = max(subscription["total_count"] - subscription["paid_count"], 0)

    async def _apply_scheduled_plan(self, subscription: Entity) -> Entity:
        scheduled = await self.store.get(EntityKind.SCHEDULED_CHANGE, subscription["id"]) or {}
        if scheduled.get("plan_id"):
            subscription["plan_id"] = scheduled["plan_id"]
        subscription["has_scheduled_changes"] = False
        subscription["change_scheduled_at"] = None
        await self.store.put(EntityKind.SCHEDULED_CHANGE, subscription["id"], {})
        return await require(self.store, EntityKind.PLAN, subscription["plan_id"])

    async def transition_subscription(self, subscription_id: str, event: SubscriptionEvent) -> SubscriptionTransition:
        subscription = await require(self.store, EntityKind.SUBSCRIPTION, subscription_id)
        status = SubscriptionStatus(subscription["status"])
        payment: Entity | None = None
        match event:
            case SubscriptionEvent.ACTIVATED:
                self._expect(event, status, {SubscriptionStatus.AUTHENTICATED})
                plan = await require(self.store, EntityKind.PLAN, subscription["plan_id"])
                self._open_period(subscription, plan, continuing=False)
                subscription["paid_count"] = max(subscription["paid_count"], 1)
                payment = await self._first_payment(subscription_id)
            case SubscriptionEvent.CHARGED:
                payment = await self._charge(subscription, status)
            case SubscriptionEvent.PENDING:
                self._expect(event, status, {SubscriptionStatus.ACTIVE})
                subscription["status"] = SubscriptionStatus.PENDING.value
            case SubscriptionEvent.HALTED:
                self._expect(event, status, {SubscriptionStatus.ACTIVE, SubscriptionStatus.PENDING})
                subscription["status"] = SubscriptionStatus.HALTED.value
            case SubscriptionEvent.CANCELLED:
                self._expect(event, status, set(SubscriptionStatus) - TERMINAL_STATUSES)
                subscription["status"] = SubscriptionStatus.CANCELLED.value
                subscription["ended_at"] = epoch(self.clock.now())
                subscription["has_scheduled_changes"] = False
                subscription["change_scheduled_at"] = None
                await self.store.put(EntityKind.SCHEDULED_CHANGE, subscription_id, {})
            case SubscriptionEvent.COMPLETED:
                self._expect(event, status, {SubscriptionStatus.ACTIVE})
                if subscription["paid_count"] < subscription["total_count"]:
                    raise FakeRazorpayStateError("not every billing cycle has been charged")
                subscription["status"] = SubscriptionStatus.COMPLETED.value
                subscription["ended_at"] = epoch(self.clock.now())
            case SubscriptionEvent.PAUSED:
                self._expect(event, status, {SubscriptionStatus.ACTIVE})
                subscription["status"] = SubscriptionStatus.PAUSED.value
            case SubscriptionEvent.RESUMED:
                self._expect(event, status, {SubscriptionStatus.PAUSED})
                subscription["status"] = SubscriptionStatus.ACTIVE.value
            case SubscriptionEvent.UPDATED:
                self._expect(event, status, set(SubscriptionStatus) - TERMINAL_STATUSES)
        self._sync_counts(subscription)
        await self.store.put(EntityKind.SUBSCRIPTION, subscription_id, subscription)
        return SubscriptionTransition(subscription=subscription, payment=payment)

    async def _charge(self, subscription: Entity, status: SubscriptionStatus) -> Entity:
        self._expect(SubscriptionEvent.CHARGED, status, CHARGEABLE)
        if subscription["paid_count"] >= subscription["total_count"]:
            raise FakeRazorpayStateError("every billing cycle has already been charged")
        scheduled = await self.store.get(EntityKind.SCHEDULED_CHANGE, subscription["id"]) or {}
        if scheduled.get("cancel"):
            raise FakeRazorpayStateError("the subscription is scheduled to be cancelled at the cycle end")
        plan = await self._apply_scheduled_plan(subscription)
        if status is SubscriptionStatus.AUTHENTICATED:
            payment = await self._first_payment(subscription["id"])
            if payment is None:
                raise FakeRazorpayStateError("the subscription has no authorization payment")
            self._open_period(subscription, plan, continuing=False)
            subscription["paid_count"] = max(subscription["paid_count"], 1)
            return payment
        payment = await self._subscription_payment(subscription, plan)
        self._open_period(subscription, plan, continuing=status is SubscriptionStatus.ACTIVE)
        subscription["paid_count"] += 1
        return payment

    @staticmethod
    def _expect(event: SubscriptionEvent, status: SubscriptionStatus, allowed: Collection[SubscriptionStatus]) -> None:
        if status not in allowed:
            raise FakeRazorpayStateError(f"cannot apply {event.value} to a {status.value} subscription")

    async def settle_refund(self, refund_id: str, outcome: RefundOutcome) -> RefundSettlement:
        refund = await require(self.store, EntityKind.REFUND, refund_id)
        if refund["status"] != RefundStatus.PENDING:
            raise FakeRazorpayStateError("only a pending refund can be settled")
        payment = await require(self.store, EntityKind.PAYMENT, refund["payment_id"])
        refund["status"] = outcome.value
        if outcome is RefundOutcome.FAILED:
            payment["amount_refunded"] -= refund["amount"]
            if payment["amount_refunded"] == 0:
                payment["status"] = PaymentStatus.CAPTURED.value
                payment["refund_status"] = None
            else:
                payment["status"] = PaymentStatus.PARTIALLY_REFUNDED.value
                payment["refund_status"] = "partial"
            await self.store.put(EntityKind.PAYMENT, payment["id"], payment)
        await self.store.put(EntityKind.REFUND, refund_id, refund)
        return RefundSettlement(refund=refund, payment=payment)

    async def last_subscription_payment(self, subscription_id: str) -> Entity | None:
        members = await self.store.members("subscription_payments", subscription_id)
        return await self.store.get(EntityKind.PAYMENT, members[-1]) if members else None
