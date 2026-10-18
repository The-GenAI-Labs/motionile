from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import Clock
from motionile.modules.audit import ActorType, AuditEvent
from motionile.modules.billing.exceptions import LiveSubscriptionConflictError
from motionile.modules.billing.ports import Alert, AuditRecorder
from motionile.modules.billing.razorpay.models import RazorpayPayment, RazorpaySubscription
from motionile.modules.billing.records import JsonObject, ProductRecord, SubscriptionRecord, WebhookEventRecord
from motionile.modules.billing.repository import BillingStore
from motionile.modules.billing.services.notices import (
    ChargeSummary,
    NoticeSender,
    cancellation_notice,
    charge_failed_notice,
    charge_notice,
    ended_notice,
    halted_notice,
)
from motionile.modules.billing.services.payment_events import PaymentContainer
from motionile.modules.billing.services.subscription_charges import Charge, ChargeRecorder, ChargeResult
from motionile.modules.billing.services.subscription_logic import (
    ACTIVATABLE,
    CHARGE_ACTIVATES,
    INVALID_TRANSITION,
    STALE_EVENT,
    Move,
    Values,
    decide_move,
    is_stale,
    merged_period,
    newest_event_time,
    plan_cancellation,
    plan_switch,
)
from motionile.modules.billing.services.webhook_registry import (
    PROCESSED,
    UNKNOWN_ENTITY,
    HandlerRegistry,
    Outcome,
    ignored,
)
from motionile.modules.billing.states import ENDED_SUBSCRIPTION_STATUSES, SubscriptionStatus
from motionile.modules.billing.transitions import transition_subscription

SUBSCRIPTION_PRODUCT_KIND = "subscription"
MISSING_PAYMENT = "missing_payment"
PAYMENT_NOT_CAPTURED = "payment_not_captured"
DUPLICATE_LIVE_SUBSCRIPTION = "duplicate_live_subscription"
SUBSCRIPTION_ID_NOTE = "subscriptionId"

type StoreFactoryPort = Callable[[AsyncSession], BillingStore]


class SubscriptionContainer(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    entity: RazorpaySubscription


class SubscriptionContents(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    subscription: SubscriptionContainer | None = None
    payment: PaymentContainer | None = None


class SubscriptionEventBody(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    payload: SubscriptionContents = Field(default_factory=SubscriptionContents)


@dataclass(frozen=True)
class SubscriptionPayload:
    subscription: RazorpaySubscription
    payment: RazorpayPayment | None


def parse_payload(payload: JsonObject) -> SubscriptionPayload | None:
    contents = SubscriptionEventBody.model_validate(payload).payload
    if contents.subscription is None:
        return None
    return SubscriptionPayload(
        contents.subscription.entity, contents.payment.entity if contents.payment is not None else None
    )


def parse_local_id(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


class Result(StrEnum):
    APPLIED = "applied"
    UNCHANGED = "unchanged"
    STALE = "stale"
    REJECTED = "rejected"
    CONFLICT = "conflict"


OUTCOME_BY_RESULT = {
    Result.APPLIED: PROCESSED,
    Result.UNCHANGED: PROCESSED,
    Result.STALE: ignored(STALE_EVENT),
    Result.REJECTED: ignored(INVALID_TRANSITION),
    Result.CONFLICT: ignored(DUPLICATE_LIVE_SUBSCRIPTION),
}


@dataclass(frozen=True)
class Delivery:
    session: AsyncSession
    store: BillingStore
    event: WebhookEventRecord
    remote: RazorpaySubscription
    payment: RazorpayPayment | None
    subscription: SubscriptionRecord

    @property
    def stale(self) -> bool:
        return is_stale(self.event.event_created_at, self.subscription.last_event_at)

    def event_values(self) -> Values:
        newest = newest_event_time(self.subscription.last_event_at, self.event.event_created_at)
        return {"last_event_at": newest} if newest is not None else {}


@dataclass(frozen=True)
class SubscriptionHandlerPorts:
    store_factory: StoreFactoryPort
    audit: AuditRecorder
    alert: Alert
    notices: NoticeSender


class SubscriptionEventHandlers:
    def __init__(self, clock: Clock, charges: ChargeRecorder, ports: SubscriptionHandlerPorts) -> None:
        self._clock = clock
        self._charges = charges
        self._store_factory = ports.store_factory
        self._audit = ports.audit
        self._alert = ports.alert
        self._notices = ports.notices

    def register(self, registry: HandlerRegistry) -> None:
        registry.register_handler("subscription.activated", self.activated)
        registry.register_handler("subscription.charged", self.charged)
        registry.register_handler("subscription.pending", self.pending)
        registry.register_handler("subscription.halted", self.halted)
        registry.register_handler("subscription.cancelled", self.cancelled)
        registry.register_handler("subscription.completed", self.completed)
        registry.register_handler("subscription.paused", self.paused)
        registry.register_handler("subscription.resumed", self.resumed)
        registry.register_handler("subscription.updated", self.updated)

    async def activated(self, session: AsyncSession, event: WebhookEventRecord) -> Outcome:
        delivery = await self._open(session, event)
        if delivery is None:
            return ignored(UNKNOWN_ENTITY)
        if delivery.subscription.status not in ACTIVATABLE:
            return PROCESSED
        return OUTCOME_BY_RESULT[await self._status_event(delivery, SubscriptionStatus.ACTIVE, "activated")]

    async def pending(self, session: AsyncSession, event: WebhookEventRecord) -> Outcome:
        delivery = await self._open(session, event)
        if delivery is None:
            return ignored(UNKNOWN_ENTITY)
        result = await self._status_event(delivery, SubscriptionStatus.PENDING, "pending")
        if result is Result.APPLIED:
            product = await self._product(delivery.store, delivery.subscription.product_id)
            await self._notices(
                session,
                charge_failed_notice(delivery.subscription.user_id, product.name, delivery.remote.charge_at_utc),
            )
        return OUTCOME_BY_RESULT[result]

    async def halted(self, session: AsyncSession, event: WebhookEventRecord) -> Outcome:
        delivery = await self._open(session, event)
        if delivery is None:
            return ignored(UNKNOWN_ENTITY)
        result = await self._status_event(delivery, SubscriptionStatus.HALTED, "halted")
        if result is Result.APPLIED:
            product = await self._product(delivery.store, delivery.subscription.product_id)
            await self._notices(session, halted_notice(delivery.subscription.user_id, product.name))
        return OUTCOME_BY_RESULT[result]

    async def paused(self, session: AsyncSession, event: WebhookEventRecord) -> Outcome:
        delivery = await self._open(session, event)
        if delivery is None:
            return ignored(UNKNOWN_ENTITY)
        return OUTCOME_BY_RESULT[await self._status_event(delivery, SubscriptionStatus.PAUSED, "paused")]

    async def resumed(self, session: AsyncSession, event: WebhookEventRecord) -> Outcome:
        delivery = await self._open(session, event)
        if delivery is None:
            return ignored(UNKNOWN_ENTITY)
        return OUTCOME_BY_RESULT[await self._status_event(delivery, SubscriptionStatus.ACTIVE, "resumed")]

    async def completed(self, session: AsyncSession, event: WebhookEventRecord) -> Outcome:
        delivery = await self._open(session, event)
        if delivery is None:
            return ignored(UNKNOWN_ENTITY)
        ended_at = delivery.remote.ended_at_utc or self._clock.now()
        result = await self._status_event(delivery, SubscriptionStatus.COMPLETED, "completed", {"ended_at": ended_at})
        return OUTCOME_BY_RESULT[result]

    async def cancelled(self, session: AsyncSession, event: WebhookEventRecord) -> Outcome:
        delivery = await self._open(session, event)
        if delivery is None:
            return ignored(UNKNOWN_ENTITY)
        subscription = delivery.subscription
        if delivery.stale:
            return ignored(STALE_EVENT)
        if subscription.status in ENDED_SUBSCRIPTION_STATUSES:
            return PROCESSED if subscription.status is SubscriptionStatus.CANCELLED else ignored(INVALID_TRANSITION)
        now = self._clock.now()
        period_end = delivery.remote.current_end_utc or subscription.current_period_end
        flags: Values = {
            "cancel_at_period_end": True,
            "cancelled_at": subscription.cancelled_at or delivery.event.event_created_at or now,
        }
        product = await self._product(delivery.store, subscription.product_id)
        if plan_cancellation(subscription.status, period_end, now).end_now:
            ended_at = delivery.remote.ended_at_utc or now
            result = await self._status_event(
                delivery, SubscriptionStatus.CANCELLED, "cancelled", {**flags, "ended_at": ended_at}
            )
            if result is Result.APPLIED and subscription.status is not SubscriptionStatus.CREATED:
                await self._notices(session, ended_notice(subscription.user_id, product.name))
            return OUTCOME_BY_RESULT[result]
        values: Values = {**merged_period(subscription, delivery.remote), **delivery.event_values(), **flags}
        await delivery.store.update_subscription(subscription.id, values)
        await self._record(delivery, "billing.subscription.cancel_scheduled", {"periodEnd": iso(period_end)})
        if not subscription.cancel_at_period_end:
            await self._notices(session, cancellation_notice(subscription.user_id, product.name, period_end))
        return PROCESSED

    async def updated(self, session: AsyncSession, event: WebhookEventRecord) -> Outcome:
        delivery = await self._open(session, event)
        if delivery is None:
            return ignored(UNKNOWN_ENTITY)
        if delivery.stale:
            return ignored(STALE_EVENT)
        subscription = delivery.subscription
        plan_product = await self._plan_product(delivery.store, delivery.remote.plan_id)
        values: Values = {
            **merged_period(subscription, delivery.remote),
            **plan_switch(subscription, plan_product),
            **delivery.event_values(),
            "total_count": delivery.remote.total_count,
        }
        await delivery.store.update_subscription(subscription.id, values)
        await self._record(delivery, "billing.subscription.updated", {"planId": delivery.remote.plan_id})
        return PROCESSED

    async def charged(self, session: AsyncSession, event: WebhookEventRecord) -> Outcome:
        delivery = await self._open(session, event)
        if delivery is None:
            self._alert("billing.unknown_subscription_charge", event_row_id=str(event.id))
            return ignored(UNKNOWN_ENTITY)
        payment = delivery.payment
        if payment is None:
            return ignored(MISSING_PAYMENT)
        if not payment.is_captured:
            return ignored(PAYMENT_NOT_CAPTURED)
        subscription = delivery.subscription
        plan_product = await self._plan_product(delivery.store, delivery.remote.plan_id)
        product = plan_product or await self._product(delivery.store, subscription.product_id)
        result = await self._charges.record(
            Charge(session, delivery.store, subscription, delivery.remote, payment, product)
        )
        outcome = await self._apply_charge(delivery, plan_product)
        await self._announce_charge(delivery, result, product)
        return outcome

    async def _apply_charge(self, delivery: Delivery, plan_product: ProductRecord | None) -> Outcome:
        subscription = delivery.subscription
        if subscription.status in ENDED_SUBSCRIPTION_STATUSES:
            self._alert(
                "billing.charge_on_ended_subscription",
                subscription_id=str(subscription.id),
                status=subscription.status.value,
                razorpay_payment_id=delivery.payment.id if delivery.payment is not None else None,
            )
            return ignored(STALE_EVENT) if delivery.stale else PROCESSED
        if delivery.stale:
            return ignored(STALE_EVENT)
        if subscription.status not in CHARGE_ACTIVATES:
            return PROCESSED
        result = await self._move(delivery, SubscriptionStatus.ACTIVE, plan_switch(subscription, plan_product))
        if result is Result.APPLIED:
            await self._record(delivery, "billing.subscription.renewed", {"paidCount": delivery.remote.paid_count})
        return OUTCOME_BY_RESULT[result]

    async def _announce_charge(self, delivery: Delivery, result: ChargeResult, product: ProductRecord) -> None:
        if not result.recorded_now or result.credits_granted <= 0 or delivery.payment is None:
            return
        await self._notices(
            delivery.session,
            charge_notice(
                delivery.subscription.user_id,
                ChargeSummary(
                    plan_name=product.name,
                    amount_paise=delivery.payment.amount,
                    currency=delivery.payment.currency,
                    credit_count=result.credits_granted,
                    next_charge_at=delivery.remote.charge_at_utc,
                ),
                first=result.first_charge,
            ),
        )

    async def _status_event(
        self, delivery: Delivery, target: SubscriptionStatus, name: str, extra: Values | None = None
    ) -> Result:
        result = await self._move(delivery, target, extra)
        if result is Result.APPLIED:
            await self._record(
                delivery,
                f"billing.subscription.{name}",
                {"from": delivery.subscription.status.value, "to": target.value},
            )
        return result

    async def _move(self, delivery: Delivery, target: SubscriptionStatus, extra: Values | None = None) -> Result:
        subscription = delivery.subscription
        if delivery.stale:
            return Result.STALE
        move = decide_move(subscription.status, target)
        if move is Move.NOOP:
            return Result.UNCHANGED
        if move is Move.REJECT:
            return Result.REJECTED
        values: Values = {**merged_period(subscription, delivery.remote), **delivery.event_values(), **(extra or {})}
        try:
            moved = await transition_subscription(delivery.store, subscription.id, subscription.status, target, values)
        except LiveSubscriptionConflictError:
            self._alert(
                "billing.duplicate_live_subscription",
                subscription_id=str(subscription.id),
                user_id=str(subscription.user_id),
                razorpay_subscription_id=delivery.remote.id,
            )
            return Result.CONFLICT
        return Result.APPLIED if moved else Result.UNCHANGED

    async def _open(self, session: AsyncSession, event: WebhookEventRecord) -> Delivery | None:
        parsed = parse_payload(event.payload)
        if parsed is None:
            return None
        store = self._store_factory(session)
        subscription = await self._resolve(store, parsed.subscription)
        if subscription is None:
            return None
        return Delivery(session, store, event, parsed.subscription, parsed.payment, subscription)

    async def _resolve(self, store: BillingStore, remote: RazorpaySubscription) -> SubscriptionRecord | None:
        found = await store.lock_subscription_by_razorpay_id(remote.id)
        if found is not None:
            return found
        local_id = parse_local_id(remote.notes.get(SUBSCRIPTION_ID_NOTE))
        if local_id is None:
            return None
        candidate = await store.lock_subscription(local_id)
        if candidate is None or candidate.razorpay_subscription_id is not None:
            return None
        await store.update_subscription(candidate.id, {"razorpay_subscription_id": remote.id})
        return replace(candidate, razorpay_subscription_id=remote.id)

    async def _plan_product(self, store: BillingStore, plan_id: str) -> ProductRecord | None:
        product = await store.product_by_plan_id(plan_id)
        return product if product is not None and product.kind == SUBSCRIPTION_PRODUCT_KIND else None

    async def _product(self, store: BillingStore, product_id: UUID) -> ProductRecord:
        product = await store.product_by_id(product_id)
        if product is None:
            message = f"product {product_id} is referenced by a subscription but does not exist"
            raise LookupError(message)
        return product

    async def _record(self, delivery: Delivery, action: str, metadata: dict[str, object]) -> None:
        await self._audit(
            delivery.session,
            AuditEvent(
                action=action,
                actor_type=ActorType.SYSTEM,
                target_type="subscription",
                target_id=str(delivery.subscription.id),
                metadata={
                    "userId": str(delivery.subscription.user_id),
                    "razorpaySubscriptionId": delivery.remote.id,
                    "webhookEvent": delivery.event.event_type,
                    **metadata,
                },
            ),
        )


def iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment is not None else None
