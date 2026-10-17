from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.credits import FakeAudit, FakeCreditsStore

from motionile.core.clock import Clock
from motionile.core.ids import new_id
from motionile.core.pagination import Cursor
from motionile.modules.billing.records import (
    CustomerRecord,
    HistoryRow,
    NewOrder,
    NewPayment,
    NewWebhookEvent,
    OrderRecord,
    OrderView,
    PaymentRecord,
    ProductRecord,
    RequeueQuery,
    RunOutcome,
    SampleProductSpec,
    WebhookEventRecord,
)
from motionile.modules.billing.services.receipts import PaymentReceipt
from motionile.modules.billing.states import (
    OrderStatus,
    PaymentRecordStatus,
    WebhookEventStatus,
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
        )

    def restore(self, state: BillingState) -> None:
        self.products = dict(state.products)
        self.orders = dict(state.orders)
        self.payments = dict(state.payments)
        self.customers = dict(state.customers)
        self.events = dict(state.events)
        self.runs = dict(state.runs)
        self.run_types = dict(state.run_types)

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
            subscription_id=None,
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
            subscription_id=None,
            user_id=payment.user_id,
            razorpay_payment_id=payment.razorpay_payment_id,
            amount_paise=payment.amount_paise,
            currency=payment.currency,
            status=payment.status,
            method=payment.method,
            fee_paise=payment.fee_paise,
            tax_paise=payment.tax_paise,
            credits_granted=0,
            refunded_paise=0,
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


@dataclass
class BillingWorld:
    clock: Clock
    billing: FakeBillingStore
    credits: FakeCreditsStore
    audit: FakeAudit
    alerts: list[tuple[str, dict[str, Any]]]
    receipts: list[PaymentReceipt]

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
