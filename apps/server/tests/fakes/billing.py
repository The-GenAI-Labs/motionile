from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.credits import FakeAudit, FakeCreditsStore

from motionile.core.clock import Clock
from motionile.core.ids import new_id
from motionile.core.pagination import Cursor
from motionile.modules.billing.exceptions import LiveSubscriptionConflictError
from motionile.modules.billing.records import (
    CustomerRecord,
    HistoryRow,
    NewOrder,
    NewPayment,
    NewRefund,
    NewSubscription,
    NewWebhookEvent,
    OrderRecord,
    OrderView,
    PaymentRecord,
    ProductRecord,
    RefundRecord,
    RequeueQuery,
    RunClaim,
    RunOutcome,
    SampleProductSpec,
    SubscriptionRecord,
    WebhookEventRecord,
)
from motionile.modules.billing.services.notices import BillingNotice
from motionile.modules.billing.services.receipts import PaymentReceipt
from motionile.modules.billing.states import (
    LIVE_SUBSCRIPTION_STATUSES,
    OrderStatus,
    PaymentRecordStatus,
    RefundStatus,
    RunStatus,
    SubscriptionStatus,
    WebhookEventStatus,
)

CAPTURED_FAMILY = frozenset(
    {PaymentRecordStatus.CAPTURED, PaymentRecordStatus.PARTIALLY_REFUNDED, PaymentRecordStatus.REFUNDED}
)


class UniqueViolationError(AssertionError):
    pass


@dataclass(frozen=True)
class BillingState:
    products: dict[UUID, ProductRecord]
    orders: dict[UUID, OrderRecord]
    payments: dict[UUID, PaymentRecord]
    customers: dict[UUID, CustomerRecord]
    events: dict[UUID, WebhookEventRecord]
    runs: dict[UUID, RunOutcome | None]
    run_types: dict[UUID, str]
    subscriptions: dict[UUID, SubscriptionRecord] = field(default_factory=dict[UUID, SubscriptionRecord])
    refunds: dict[UUID, RefundRecord] = field(default_factory=dict[UUID, RefundRecord])
    run_periods: dict[UUID, tuple[datetime, datetime]] = field(default_factory=dict[UUID, tuple[datetime, datetime]])
    run_started: dict[UUID, datetime] = field(default_factory=dict[UUID, datetime])


class FakeBillingStore:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.products: dict[UUID, ProductRecord] = {}
        self.orders: dict[UUID, OrderRecord] = {}
        self.payments: dict[UUID, PaymentRecord] = {}
        self.customers: dict[UUID, CustomerRecord] = {}
        self.events: dict[UUID, WebhookEventRecord] = {}
        self.runs: dict[UUID, RunOutcome | None] = {}
        self.run_types: dict[UUID, str] = {}
        self.subscriptions: dict[UUID, SubscriptionRecord] = {}
        self.refunds: dict[UUID, RefundRecord] = {}
        self.run_periods: dict[UUID, tuple[datetime, datetime]] = {}
        self.run_started: dict[UUID, datetime] = {}
        self.pending_candidates: list[UUID] = []

    def __call__(self, session: AsyncSession) -> "FakeBillingStore":
        del session
        return self

    def snapshot(self) -> BillingState:
        return BillingState(
            dict(self.products),
            dict(self.orders),
            dict(self.payments),
            dict(self.customers),
            dict(self.events),
            dict(self.runs),
            dict(self.run_types),
            dict(self.subscriptions),
            dict(self.refunds),
            dict(self.run_periods),
            dict(self.run_started),
        )

    def restore(self, state: BillingState) -> None:
        self.products = dict(state.products)
        self.orders = dict(state.orders)
        self.payments = dict(state.payments)
        self.customers = dict(state.customers)
        self.events = dict(state.events)
        self.runs = dict(state.runs)
        self.run_types = dict(state.run_types)
        self.subscriptions = dict(state.subscriptions)
        self.refunds = dict(state.refunds)
        self.run_periods = dict(state.run_periods)
        self.run_started = dict(state.run_started)

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession]:
        state = self.snapshot()
        session = AsyncSession()
        try:
            yield session
        except BaseException:
            self.restore(state)
            raise
        finally:
            await session.close()

    def add_product(self, product: ProductRecord) -> ProductRecord:
        self.products[product.id] = product
        return product

    async def active_products(self) -> list[ProductRecord]:
        active = [product for product in self.products.values() if product.is_active]
        return sorted(active, key=lambda product: (product.kind, product.sort_order, product.code))

    async def product_by_code(self, code: str) -> ProductRecord | None:
        return next((product for product in self.products.values() if product.code == code), None)

    async def product_by_id(self, product_id: UUID) -> ProductRecord | None:
        return self.products.get(product_id)

    async def share_product_by_code(self, code: str) -> ProductRecord | None:
        return await self.product_by_code(code)

    async def share_product_by_id(self, product_id: UUID) -> ProductRecord | None:
        return await self.product_by_id(product_id)

    async def lock_creation(self, key: UUID) -> bool:
        del key
        return True

    async def save_sample_product(self, spec: SampleProductSpec) -> ProductRecord | None:
        existing = await self.product_by_code(spec.code)
        if existing is not None:
            if not existing.is_sample:
                return None
            updated = replace(
                existing,
                name=spec.name,
                description=spec.description,
                sort_order=spec.sort_order,
                features=spec.features,
            )
            self.products[existing.id] = updated
            return updated
        created = ProductRecord(
            id=new_id(),
            code=spec.code,
            kind=spec.kind,
            plan_key=spec.plan_key,
            name=spec.name,
            description=spec.description,
            price_paise=spec.price_paise,
            currency="INR",
            interval=spec.interval,
            credits_granted=spec.credits_granted,
            razorpay_plan_id=None,
            is_active=spec.kind == "credit_pack",
            is_sample=True,
            sort_order=spec.sort_order,
            features=spec.features,
            version=1,
        )
        self.products[created.id] = created
        return created

    async def activate_product_with_plan(self, product_id: UUID, razorpay_plan_id: str) -> bool:
        product = self.products[product_id]
        if product.razorpay_plan_id not in {None, razorpay_plan_id}:
            return False
        self.products[product_id] = replace(product, razorpay_plan_id=razorpay_plan_id, is_active=True)
        return True

    async def customer(self, user_id: UUID) -> CustomerRecord | None:
        return self.customers.get(user_id)

    async def insert_customer(self, user_id: UUID, razorpay_customer_id: str) -> None:
        self.customers.setdefault(user_id, CustomerRecord(user_id, razorpay_customer_id))

    async def order_for_key(self, user_id: UUID, key: str) -> OrderRecord | None:
        return next(
            (order for order in self.orders.values() if order.user_id == user_id and order.idempotency_key == key),
            None,
        )

    async def insert_order(self, order: NewOrder) -> OrderRecord | None:
        if await self.order_for_key(order.user_id, order.idempotency_key) is not None:
            return None
        record = OrderRecord(
            id=order.id,
            user_id=order.user_id,
            product_id=order.product.id,
            product_version=order.product.version,
            kind=order.product.kind,
            amount_paise=order.product.price_paise,
            currency=order.product.currency,
            credits_granted=order.product.credits_granted,
            status=OrderStatus.CREATED,
            razorpay_order_id=None,
            subscription_id=order.subscription_id,
            receipt=str(order.id),
            idempotency_key=order.idempotency_key,
            failure_reason=None,
            flagged_at=None,
            flag_reason=None,
            expires_at=order.expires_at,
            paid_at=None,
            created_at=self.clock.now(),
        )
        self.orders[record.id] = record
        return record

    async def order_view(self, order_id: UUID, user_id: UUID) -> OrderView | None:
        order = self.orders.get(order_id)
        if order is None or order.user_id != user_id:
            return None
        product = self.products[order.product_id]
        return OrderView(order, product.code, product.name)

    async def lock_order(self, order_id: UUID) -> OrderRecord | None:
        return self.orders.get(order_id)

    async def lock_order_by_razorpay_id(self, razorpay_order_id: str) -> OrderRecord | None:
        return next((order for order in self.orders.values() if order.razorpay_order_id == razorpay_order_id), None)

    async def order_by_razorpay_id_for_user(self, razorpay_order_id: str, user_id: UUID) -> OrderRecord | None:
        order = await self.lock_order_by_razorpay_id(razorpay_order_id)
        return order if order is not None and order.user_id == user_id else None

    async def transition_order(
        self, order_id: UUID, expected: OrderStatus, target: OrderStatus, values: Mapping[str, object]
    ) -> bool:
        order = self.orders.get(order_id)
        if order is None or order.status is not expected:
            return False
        self.orders[order_id] = replace(order, status=target, **values)
        return True

    async def flag_order(self, order_id: UUID, reason: str, at: datetime) -> bool:
        order = self.orders[order_id]
        if order.flagged_at is not None:
            return False
        self.orders[order_id] = replace(order, flagged_at=at, flag_reason=reason)
        return True

    async def reconcilable_orders(self, before: datetime, after: Cursor | None, limit: int) -> list[OrderRecord]:
        rows = sorted(
            (
                order
                for order in self.orders.values()
                if order.status in {OrderStatus.CREATED, OrderStatus.PENDING}
                and order.flagged_at is None
                and order.created_at < before
                and (after is None or (order.created_at, order.id) > (after.created_at, after.id))
            ),
            key=lambda order: (order.created_at, order.id),
        )
        return rows[:limit]

    async def payment_by_razorpay_id(self, razorpay_payment_id: str) -> PaymentRecord | None:
        return next(
            (payment for payment in self.payments.values() if payment.razorpay_payment_id == razorpay_payment_id),
            None,
        )

    async def insert_payment(self, payment: NewPayment) -> PaymentRecord:
        if await self.payment_by_razorpay_id(payment.razorpay_payment_id) is not None:
            raise UniqueViolationError("uq_payments_razorpay_payment_id")
        record = PaymentRecord(
            id=payment.id,
            order_id=payment.order_id,
            subscription_id=payment.subscription_id,
            user_id=payment.user_id,
            razorpay_payment_id=payment.razorpay_payment_id,
            amount_paise=payment.amount_paise,
            currency=payment.currency,
            status=payment.status,
            method=payment.method,
            fee_paise=payment.fee_paise,
            tax_paise=payment.tax_paise,
            credits_granted=0,
            refunded_paise=payment.refunded_paise,
            error_code=payment.error_code,
            error_description=payment.error_description,
            captured_at=payment.captured_at,
            created_at=self.clock.now(),
        )
        self.payments[record.id] = record
        return record

    async def transition_payment(
        self,
        payment_id: UUID,
        expected: PaymentRecordStatus,
        target: PaymentRecordStatus,
        values: Mapping[str, object],
    ) -> bool:
        payment = self.payments.get(payment_id)
        if payment is None or payment.status is not expected:
            return False
        self.payments[payment_id] = replace(payment, status=target, **values)
        return True

    async def set_payment_credits(self, payment_id: UUID, amount: int) -> None:
        self.payments[payment_id] = replace(self.payments[payment_id], credits_granted=amount)

    async def insert_event(self, event: NewWebhookEvent) -> bool:
        if await self.event_by_provider_id(event.provider, event.event_id) is not None:
            return False
        self.events[event.id] = WebhookEventRecord(
            id=event.id,
            provider=event.provider,
            event_id=event.event_id,
            event_type=event.event_type,
            event_created_at=event.event_created_at,
            payload=event.payload,
            status=WebhookEventStatus.RECEIVED,
            attempts=0,
            last_error=None,
            ignored_reason=None,
            received_at=event.received_at,
            processed_at=None,
        )
        return True

    async def event_by_provider_id(self, provider: str, event_id: str) -> WebhookEventRecord | None:
        return next(
            (event for event in self.events.values() if event.provider == provider and event.event_id == event_id),
            None,
        )

    async def lock_event(self, event_row_id: UUID) -> WebhookEventRecord | None:
        return self.events.get(event_row_id)

    async def transition_event(
        self,
        event_row_id: UUID,
        expected: WebhookEventStatus,
        target: WebhookEventStatus,
        values: Mapping[str, object],
    ) -> bool:
        event = self.events.get(event_row_id)
        if event is None or event.status is not expected:
            return False
        self.events[event_row_id] = replace(event, status=target, **values)
        return True

    async def requeue_candidates(self, query: RequeueQuery) -> list[UUID]:
        del query
        return list(self.pending_candidates)

    async def start_run(self, run_id: UUID, run_type: str, now: datetime) -> None:
        del now
        self.runs[run_id] = None
        self.run_types[run_id] = run_type

    async def finish_run(self, run_id: UUID, outcome: RunOutcome) -> bool:
        if self.runs.get(run_id, outcome) is not None:
            return False
        self.runs[run_id] = outcome
        return True

    async def history(self, user_id: UUID, cursor: Cursor | None, limit: int) -> list[HistoryRow]:
        del user_id, cursor, limit
        return []

    async def product_by_plan_id(self, razorpay_plan_id: str) -> ProductRecord | None:
        return next(
            (product for product in self.products.values() if product.razorpay_plan_id == razorpay_plan_id), None
        )

    async def insert_subscription(self, subscription: NewSubscription) -> SubscriptionRecord:
        record = SubscriptionRecord(
            id=subscription.id,
            user_id=subscription.user_id,
            product_id=subscription.product_id,
            pending_product_id=None,
            razorpay_subscription_id=None,
            status=SubscriptionStatus.CREATED,
            total_count=subscription.total_count,
            paid_count=0,
            current_period_start=None,
            current_period_end=None,
            next_charge_at=None,
            cancel_at_period_end=False,
            cancelled_at=None,
            ended_at=None,
            last_event_at=None,
            created_at=self.clock.now(),
        )
        self.subscriptions[record.id] = record
        return record

    async def subscription_for_user(self, subscription_id: UUID, user_id: UUID) -> SubscriptionRecord | None:
        found = self.subscriptions.get(subscription_id)
        return found if found is not None and found.user_id == user_id else None

    async def lock_subscription_for_user(self, subscription_id: UUID, user_id: UUID) -> SubscriptionRecord | None:
        return await self.subscription_for_user(subscription_id, user_id)

    async def lock_subscription(self, subscription_id: UUID) -> SubscriptionRecord | None:
        return self.subscriptions.get(subscription_id)

    async def lock_subscription_by_razorpay_id(self, razorpay_subscription_id: str) -> SubscriptionRecord | None:
        return next(
            (
                subscription
                for subscription in self.subscriptions.values()
                if subscription.razorpay_subscription_id == razorpay_subscription_id
            ),
            None,
        )

    async def lock_subscription_by_razorpay_id_for_user(
        self, razorpay_subscription_id: str, user_id: UUID
    ) -> SubscriptionRecord | None:
        found = await self.lock_subscription_by_razorpay_id(razorpay_subscription_id)
        return found if found is not None and found.user_id == user_id else None

    async def live_subscription(self, user_id: UUID) -> SubscriptionRecord | None:
        return next(
            (
                subscription
                for subscription in self.subscriptions.values()
                if subscription.user_id == user_id and subscription.status in LIVE_SUBSCRIPTION_STATUSES
            ),
            None,
        )

    async def lock_live_subscription(self, user_id: UUID) -> SubscriptionRecord | None:
        return await self.live_subscription(user_id)

    async def transition_subscription(
        self,
        subscription_id: UUID,
        expected: SubscriptionStatus,
        target: SubscriptionStatus,
        values: Mapping[str, object],
    ) -> bool:
        subscription = self.subscriptions.get(subscription_id)
        if subscription is None or subscription.status is not expected:
            return False
        if target in LIVE_SUBSCRIPTION_STATUSES and any(
            other.id != subscription_id
            and other.user_id == subscription.user_id
            and other.status in LIVE_SUBSCRIPTION_STATUSES
            for other in self.subscriptions.values()
        ):
            raise LiveSubscriptionConflictError
        self.subscriptions[subscription_id] = replace(subscription, status=target, **values)
        return True

    async def update_subscription(self, subscription_id: UUID, values: Mapping[str, object]) -> None:
        self.subscriptions[subscription_id] = replace(self.subscriptions[subscription_id], **values)

    async def lock_subscription_order(self, subscription_id: UUID) -> OrderRecord | None:
        matches = [order for order in self.orders.values() if order.subscription_id == subscription_id]
        return min(matches, key=lambda order: (order.created_at, order.id), default=None)

    async def subscription_payment_count(self, subscription_id: UUID) -> int:
        return sum(1 for payment in self.payments.values() if payment.subscription_id == subscription_id)

    def _page(self, records: list[SubscriptionRecord], after: UUID | None, limit: int) -> list[SubscriptionRecord]:
        ordered = sorted(records, key=lambda record: record.id)
        return [record for record in ordered if after is None or record.id > after][:limit]

    async def due_cancellations(self, now: datetime, after: UUID | None, limit: int) -> list[SubscriptionRecord]:
        return self._page(
            [
                subscription
                for subscription in self.subscriptions.values()
                if subscription.status in LIVE_SUBSCRIPTION_STATUSES
                and subscription.cancel_at_period_end
                and subscription.current_period_end is not None
                and subscription.current_period_end <= now
            ],
            after,
            limit,
        )

    async def abandoned_subscriptions(self, now: datetime, after: UUID | None, limit: int) -> list[SubscriptionRecord]:
        return self._page(
            [
                subscription
                for subscription in self.subscriptions.values()
                if subscription.status is SubscriptionStatus.CREATED
                and subscription.last_event_at is None
                and any(
                    order.subscription_id == subscription.id and order.expires_at <= now
                    for order in self.orders.values()
                )
            ],
            after,
            limit,
        )

    async def live_subscriptions(self, after: UUID | None, limit: int) -> list[SubscriptionRecord]:
        return self._page(
            [
                subscription
                for subscription in self.subscriptions.values()
                if subscription.status in LIVE_SUBSCRIPTION_STATUSES
            ],
            after,
            limit,
        )

    async def unactivated_subscriptions(self, after: UUID | None, limit: int) -> list[SubscriptionRecord]:
        return self._page(
            [
                subscription
                for subscription in self.subscriptions.values()
                if subscription.status is SubscriptionStatus.CREATED
                and subscription.razorpay_subscription_id is not None
            ],
            after,
            limit,
        )

    async def payment_by_id(self, payment_id: UUID) -> PaymentRecord | None:
        return self.payments.get(payment_id)

    async def lock_payment(self, payment_id: UUID) -> PaymentRecord | None:
        return self.payments.get(payment_id)

    async def captured_payments_between(
        self, start: datetime, end: datetime, after: UUID | None, limit: int
    ) -> list[PaymentRecord]:
        matches = sorted(
            (
                payment
                for payment in self.payments.values()
                if payment.status in CAPTURED_FAMILY
                and start <= payment.created_at < end
                and (after is None or payment.id > after)
            ),
            key=lambda payment: payment.id,
        )
        return matches[:limit]

    async def pending_refund_totals(self, payment_ids: Sequence[UUID]) -> dict[UUID, int]:
        totals: dict[UUID, int] = {}
        for refund in self.refunds.values():
            if refund.payment_id in payment_ids and refund.status is RefundStatus.PENDING:
                totals[refund.payment_id] = totals.get(refund.payment_id, 0) + refund.amount_paise
        return totals

    async def clawed_back_total(self, payment_id: UUID) -> int:
        return sum(
            refund.credits_clawed_back
            for refund in self.refunds.values()
            if refund.payment_id == payment_id and refund.status is RefundStatus.PROCESSED
        )

    async def processed_refund_total(self, payment_id: UUID) -> int:
        return sum(
            refund.amount_paise
            for refund in self.refunds.values()
            if refund.payment_id == payment_id and refund.status is RefundStatus.PROCESSED
        )

    async def insert_refund(self, refund: NewRefund) -> RefundRecord:
        record = RefundRecord(
            id=refund.id,
            payment_id=refund.payment_id,
            razorpay_refund_id=refund.razorpay_refund_id,
            amount_paise=refund.amount_paise,
            status=RefundStatus.PENDING,
            reason=refund.reason,
            idempotency_key=refund.idempotency_key,
            initiated_by=refund.initiated_by,
            credits_clawed_back=0,
            failure_reason=None,
            processed_at=None,
            created_at=self.clock.now(),
        )
        self.refunds[record.id] = record
        return record

    async def refund_by_id(self, refund_id: UUID) -> RefundRecord | None:
        return self.refunds.get(refund_id)

    async def refund_by_idempotency_key(self, idempotency_key: str) -> RefundRecord | None:
        return next((refund for refund in self.refunds.values() if refund.idempotency_key == idempotency_key), None)

    async def stale_unlinked_refunds(self, before: datetime, after: UUID | None, limit: int) -> list[RefundRecord]:
        matches = sorted(
            (
                refund
                for refund in self.refunds.values()
                if refund.status is RefundStatus.PENDING
                and refund.razorpay_refund_id is None
                and refund.created_at < before
                and (after is None or refund.id > after)
            ),
            key=lambda refund: refund.id,
        )
        return matches[:limit]

    async def refund_by_razorpay_id(self, razorpay_refund_id: str) -> RefundRecord | None:
        return next(
            (refund for refund in self.refunds.values() if refund.razorpay_refund_id == razorpay_refund_id), None
        )

    async def lock_refund(self, refund_id: UUID) -> RefundRecord | None:
        return self.refunds.get(refund_id)

    async def transition_refund(
        self, refund_id: UUID, expected: RefundStatus, target: RefundStatus, values: Mapping[str, object]
    ) -> bool:
        refund = self.refunds.get(refund_id)
        if refund is None or refund.status is not expected:
            return False
        self.refunds[refund_id] = replace(refund, status=target, **values)
        return True

    async def update_refund(self, refund_id: UUID, values: Mapping[str, object]) -> None:
        self.refunds[refund_id] = replace(self.refunds[refund_id], **values)

    async def claim_settlement_run(
        self, period_start: datetime, period_end: datetime, now: datetime, stale_before: datetime
    ) -> RunClaim | None:
        existing = next(
            (
                run_id
                for run_id, period in self.run_periods.items()
                if self.run_types.get(run_id) == "settlement" and period[0] == period_start
            ),
            None,
        )
        if existing is None:
            run_id = new_id()
            self.runs[run_id] = None
            self.run_types[run_id] = "settlement"
            self.run_periods[run_id] = (period_start, period_end)
            self.run_started[run_id] = now
            return RunClaim(run_id, resumed=False)
        outcome = self.runs[existing]
        restartable = (outcome is not None and outcome.status is RunStatus.FAILED) or (
            outcome is None and self.run_started[existing] < stale_before
        )
        if not restartable:
            return None
        self.runs[existing] = None
        self.run_started[existing] = now
        return RunClaim(existing, resumed=True)


@dataclass
class BillingWorld:
    clock: Clock
    billing: FakeBillingStore
    credits: FakeCreditsStore
    audit: FakeAudit
    alerts: list[tuple[str, dict[str, Any]]]
    receipts: list[PaymentReceipt]
    notices: list[BillingNotice] = field(default_factory=list[BillingNotice])

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession]:
        billing_state = self.billing.snapshot()
        credits_state = self.credits.snapshot()
        session = AsyncSession()
        try:
            yield session
        except BaseException:
            self.billing.restore(billing_state)
            self.credits.restore(credits_state)
            raise
        finally:
            await session.close()

    def alert(self, code: str, **fields: object) -> None:
        self.alerts.append((code, dict(fields)))

    async def send_receipt(self, session: AsyncSession, receipt: PaymentReceipt) -> None:
        del session
        self.receipts.append(receipt)

    async def send_notice(self, session: AsyncSession, notice: BillingNotice) -> None:
        del session
        self.notices.append(notice)
