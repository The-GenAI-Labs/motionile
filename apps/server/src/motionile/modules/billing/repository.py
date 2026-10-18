from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    Select,
    String,
    cast,
    func,
    literal,
    null,
    select,
    text,
    tuple_,
    union_all,
    update,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.ids import new_id
from motionile.core.pagination import Cursor, keyset_page
from motionile.modules.billing.exceptions import LiveSubscriptionConflictError
from motionile.modules.billing.models import (
    BillingCustomer,
    Order,
    Payment,
    Product,
    ReconciliationRun,
    Refund,
    Subscription,
)
from motionile.modules.billing.models import WebhookEvent as WebhookEventModel
from motionile.modules.billing.records import (
    CustomerRecord,
    HistoryKind,
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
from motionile.modules.billing.states import (
    LIVE_SUBSCRIPTION_STATUSES,
    RUN_MACHINE,
    OrderStatus,
    PaymentRecordStatus,
    RefundStatus,
    RunStatus,
    SubscriptionStatus,
    WebhookEventStatus,
)

FRESH_ROWS = {"populate_existing": True}
PRODUCT_CODE_CONSTRAINT = "uq_products_code"
SAMPLE_CURRENCY = "INR"
CREDIT_PACK_KIND = "credit_pack"
ORDER_IDEMPOTENCY_CONSTRAINT = "uq_orders_user_id_idempotency_key"
EVENT_UNIQUE_CONSTRAINT = "uq_webhook_events_provider_event_id"
ERROR_LIMIT = 2000
RECONCILABLE_STATUSES = (OrderStatus.CREATED.value, OrderStatus.PENDING.value)
HIDDEN_HISTORY_STATUS = OrderStatus.CREATED.value
LIVE_SUBSCRIPTION_INDEX = "ix_subscriptions_user_id_live"
LIVE_STATUS_VALUES = tuple(status.value for status in LIVE_SUBSCRIPTION_STATUSES)
CAPTURED_FAMILY_VALUES = (
    PaymentRecordStatus.CAPTURED.value,
    PaymentRecordStatus.PARTIALLY_REFUNDED.value,
    PaymentRecordStatus.REFUNDED.value,
)
SETTLEMENT_RUN_TYPE = "settlement"
PAYMENT_TITLE_PREFIX = "Payment for "
REFUND_TITLE_PREFIX = "Refund for "
FALLBACK_SUBJECT = "your order"

REQUEUE_CANDIDATES = text(
    """
    SELECT e.id FROM webhook_events e
    WHERE e.provider = :provider
        AND (
            (e.status = 'received' AND e.received_at < :stale_before)
            OR (e.status = 'failed' AND e.attempts < :max_attempts AND e.updated_at < :stale_before)
        )
        AND NOT EXISTS (
            SELECT 1 FROM procrastinate_jobs j
            WHERE j.task_name = :task_name
                AND j.status IN ('todo', 'doing')
                AND j.args ->> 'event_row_id' = e.id::text
        )
    ORDER BY e.received_at, e.id
    LIMIT :limit
    """
)


class BillingStore(Protocol):
    async def active_products(self) -> list[ProductRecord]: ...
    async def product_by_code(self, code: str) -> ProductRecord | None: ...
    async def product_by_id(self, product_id: UUID) -> ProductRecord | None: ...
    async def save_sample_product(self, spec: SampleProductSpec) -> ProductRecord | None: ...
    async def activate_product_with_plan(self, product_id: UUID, razorpay_plan_id: str) -> bool: ...
    async def customer(self, user_id: UUID) -> CustomerRecord | None: ...
    async def insert_customer(self, user_id: UUID, razorpay_customer_id: str) -> None: ...
    async def order_for_key(self, user_id: UUID, key: str) -> OrderRecord | None: ...
    async def insert_order(self, order: NewOrder) -> OrderRecord | None: ...
    async def order_view(self, order_id: UUID, user_id: UUID) -> OrderView | None: ...
    async def lock_order(self, order_id: UUID) -> OrderRecord | None: ...
    async def lock_order_by_razorpay_id(self, razorpay_order_id: str) -> OrderRecord | None: ...
    async def order_by_razorpay_id_for_user(self, razorpay_order_id: str, user_id: UUID) -> OrderRecord | None: ...
    async def transition_order(
        self, order_id: UUID, expected: OrderStatus, target: OrderStatus, values: Mapping[str, object]
    ) -> bool: ...
    async def flag_order(self, order_id: UUID, reason: str, at: datetime) -> bool: ...
    async def reconcilable_orders(self, before: datetime, after: Cursor | None, limit: int) -> list[OrderRecord]: ...
    async def payment_by_razorpay_id(self, razorpay_payment_id: str) -> PaymentRecord | None: ...
    async def insert_payment(self, payment: NewPayment) -> PaymentRecord: ...
    async def transition_payment(
        self,
        payment_id: UUID,
        expected: PaymentRecordStatus,
        target: PaymentRecordStatus,
        values: Mapping[str, object],
    ) -> bool: ...
    async def set_payment_credits(self, payment_id: UUID, amount: int) -> None: ...
    async def insert_event(self, event: NewWebhookEvent) -> bool: ...
    async def event_by_provider_id(self, provider: str, event_id: str) -> WebhookEventRecord | None: ...
    async def lock_event(self, event_row_id: UUID) -> WebhookEventRecord | None: ...
    async def transition_event(
        self,
        event_row_id: UUID,
        expected: WebhookEventStatus,
        target: WebhookEventStatus,
        values: Mapping[str, object],
    ) -> bool: ...
    async def requeue_candidates(self, query: RequeueQuery) -> list[UUID]: ...
    async def start_run(self, run_id: UUID, run_type: str, now: datetime) -> None: ...
    async def finish_run(self, run_id: UUID, outcome: RunOutcome) -> bool: ...
    async def history(self, user_id: UUID, cursor: Cursor | None, limit: int) -> list[HistoryRow]: ...
    async def product_by_plan_id(self, razorpay_plan_id: str) -> ProductRecord | None: ...
    async def insert_subscription(self, subscription: NewSubscription) -> SubscriptionRecord: ...
    async def subscription_for_user(self, subscription_id: UUID, user_id: UUID) -> SubscriptionRecord | None: ...
    async def lock_subscription_for_user(self, subscription_id: UUID, user_id: UUID) -> SubscriptionRecord | None: ...
    async def lock_subscription(self, subscription_id: UUID) -> SubscriptionRecord | None: ...
    async def lock_subscription_by_razorpay_id(self, razorpay_subscription_id: str) -> SubscriptionRecord | None: ...
    async def lock_subscription_by_razorpay_id_for_user(
        self, razorpay_subscription_id: str, user_id: UUID
    ) -> SubscriptionRecord | None: ...
    async def live_subscription(self, user_id: UUID) -> SubscriptionRecord | None: ...
    async def lock_live_subscription(self, user_id: UUID) -> SubscriptionRecord | None: ...
    async def transition_subscription(
        self,
        subscription_id: UUID,
        expected: SubscriptionStatus,
        target: SubscriptionStatus,
        values: Mapping[str, object],
    ) -> bool: ...
    async def update_subscription(self, subscription_id: UUID, values: Mapping[str, object]) -> None: ...
    async def lock_subscription_order(self, subscription_id: UUID) -> OrderRecord | None: ...
    async def subscription_payment_count(self, subscription_id: UUID) -> int: ...
    async def due_cancellations(self, now: datetime, after: UUID | None, limit: int) -> list[SubscriptionRecord]: ...
    async def abandoned_subscriptions(
        self, now: datetime, after: UUID | None, limit: int
    ) -> list[SubscriptionRecord]: ...
    async def live_subscriptions(self, after: UUID | None, limit: int) -> list[SubscriptionRecord]: ...
    async def unactivated_subscriptions(self, after: UUID | None, limit: int) -> list[SubscriptionRecord]: ...
    async def payment_by_id(self, payment_id: UUID) -> PaymentRecord | None: ...
    async def lock_payment(self, payment_id: UUID) -> PaymentRecord | None: ...
    async def captured_payments_between(
        self, start: datetime, end: datetime, after: UUID | None, limit: int
    ) -> list[PaymentRecord]: ...
    async def pending_refund_totals(self, payment_ids: Sequence[UUID]) -> dict[UUID, int]: ...
    async def clawed_back_total(self, payment_id: UUID) -> int: ...
    async def insert_refund(self, refund: NewRefund) -> RefundRecord: ...
    async def refund_by_id(self, refund_id: UUID) -> RefundRecord | None: ...
    async def refund_by_razorpay_id(self, razorpay_refund_id: str) -> RefundRecord | None: ...
    async def lock_refund(self, refund_id: UUID) -> RefundRecord | None: ...
    async def transition_refund(
        self, refund_id: UUID, expected: RefundStatus, target: RefundStatus, values: Mapping[str, object]
    ) -> bool: ...
    async def update_refund(self, refund_id: UUID, values: Mapping[str, object]) -> None: ...
    async def claim_settlement_run(
        self, period_start: datetime, period_end: datetime, now: datetime, stale_before: datetime
    ) -> RunClaim | None: ...


def subscription_record(row: Subscription) -> SubscriptionRecord:
    return SubscriptionRecord(
        id=row.id,
        user_id=row.user_id,
        product_id=row.product_id,
        pending_product_id=row.pending_product_id,
        razorpay_subscription_id=row.razorpay_subscription_id,
        status=SubscriptionStatus(row.status),
        total_count=row.total_count,
        paid_count=row.paid_count,
        current_period_start=row.current_period_start,
        current_period_end=row.current_period_end,
        next_charge_at=row.next_charge_at,
        cancel_at_period_end=row.cancel_at_period_end,
        cancelled_at=row.cancelled_at,
        ended_at=row.ended_at,
        last_event_at=row.last_event_at,
        created_at=row.created_at,
    )


def refund_record(row: Refund) -> RefundRecord:
    return RefundRecord(
        id=row.id,
        payment_id=row.payment_id,
        razorpay_refund_id=row.razorpay_refund_id,
        amount_paise=row.amount_paise,
        status=RefundStatus(row.status),
        reason=row.reason,
        initiated_by=row.initiated_by,
        credits_clawed_back=row.credits_clawed_back,
        failure_reason=row.failure_reason,
        processed_at=row.processed_at,
        created_at=row.created_at,
    )


def product_record(row: Product) -> ProductRecord:
    return ProductRecord(
        id=row.id,
        code=row.code,
        kind=row.kind,
        plan_key=row.plan_key,
        name=row.name,
        description=row.description,
        price_paise=row.price_paise,
        currency=row.currency,
        interval=row.interval,
        credits_granted=row.credits_granted,
        razorpay_plan_id=row.razorpay_plan_id,
        is_active=row.is_active,
        is_sample=row.is_sample,
        sort_order=row.sort_order,
        features=tuple(item for item in row.features if isinstance(item, str)),
        version=row.version,
    )


def order_record(row: Order) -> OrderRecord:
    return OrderRecord(
        id=row.id,
        user_id=row.user_id,
        product_id=row.product_id,
        product_version=row.product_version,
        kind=row.kind,
        amount_paise=row.amount_paise,
        currency=row.currency,
        credits_granted=row.credits_granted,
        status=OrderStatus(row.status),
        razorpay_order_id=row.razorpay_order_id,
        subscription_id=row.subscription_id,
        receipt=row.receipt,
        idempotency_key=row.idempotency_key,
        failure_reason=row.failure_reason,
        flagged_at=row.flagged_at,
        flag_reason=row.flag_reason,
        expires_at=row.expires_at,
        paid_at=row.paid_at,
        created_at=row.created_at,
    )


def payment_record(row: Payment) -> PaymentRecord:
    return PaymentRecord(
        id=row.id,
        order_id=row.order_id,
        subscription_id=row.subscription_id,
        user_id=row.user_id,
        razorpay_payment_id=row.razorpay_payment_id,
        amount_paise=row.amount_paise,
        currency=row.currency,
        status=PaymentRecordStatus(row.status),
        method=row.method,
        fee_paise=row.fee_paise,
        tax_paise=row.tax_paise,
        credits_granted=row.credits_granted,
        refunded_paise=row.refunded_paise,
        error_code=row.error_code,
        error_description=row.error_description,
        captured_at=row.captured_at,
        created_at=row.created_at,
    )


def event_record(row: WebhookEventModel) -> WebhookEventRecord:
    return WebhookEventRecord(
        id=row.id,
        provider=row.provider,
        event_id=row.event_id,
        event_type=row.event_type,
        event_created_at=row.event_created_at,
        payload=row.payload,
        status=WebhookEventStatus(row.status),
        attempts=row.attempts,
        last_error=row.last_error,
        ignored_reason=row.ignored_reason,
        received_at=row.received_at,
        processed_at=row.processed_at,
    )


class SqlBillingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def active_products(self) -> list[ProductRecord]:
        rows = await self.session.scalars(
            select(Product)
            .where(Product.is_active.is_(True))
            .order_by(Product.kind, Product.sort_order, Product.code)
            .execution_options(**FRESH_ROWS)
        )
        return [product_record(row) for row in rows]

    async def product_by_code(self, code: str) -> ProductRecord | None:
        row = await self.session.scalar(select(Product).where(Product.code == code).execution_options(**FRESH_ROWS))
        return product_record(row) if row is not None else None

    async def product_by_id(self, product_id: UUID) -> ProductRecord | None:
        row = await self.session.scalar(select(Product).where(Product.id == product_id).execution_options(**FRESH_ROWS))
        return product_record(row) if row is not None else None

    async def save_sample_product(self, spec: SampleProductSpec) -> ProductRecord | None:
        saved = await self.session.scalar(
            pg_insert(Product)
            .values(
                id=new_id(),
                code=spec.code,
                kind=spec.kind,
                plan_key=spec.plan_key,
                name=spec.name,
                description=spec.description,
                price_paise=spec.price_paise,
                currency=SAMPLE_CURRENCY,
                interval=spec.interval,
                credits_granted=spec.credits_granted,
                is_active=spec.kind == CREDIT_PACK_KIND,
                is_sample=True,
                sort_order=spec.sort_order,
                features=list(spec.features),
            )
            .on_conflict_do_update(
                constraint=PRODUCT_CODE_CONSTRAINT,
                set_={
                    "name": spec.name,
                    "description": spec.description,
                    "sort_order": spec.sort_order,
                    "features": list(spec.features),
                    "updated_at": func.now(),
                },
                where=Product.is_sample.is_(True),
            )
            .returning(Product.id)
        )
        return await self.product_by_id(saved) if saved is not None else None

    async def activate_product_with_plan(self, product_id: UUID, razorpay_plan_id: str) -> bool:
        changed = await self.session.scalar(
            update(Product)
            .where(
                Product.id == product_id,
                (Product.razorpay_plan_id.is_(None)) | (Product.razorpay_plan_id == razorpay_plan_id),
            )
            .values(razorpay_plan_id=razorpay_plan_id, is_active=True)
            .returning(Product.id)
        )
        return changed is not None

    async def customer(self, user_id: UUID) -> CustomerRecord | None:
        row = await self.session.scalar(
            select(BillingCustomer).where(BillingCustomer.user_id == user_id).execution_options(**FRESH_ROWS)
        )
        return CustomerRecord(row.user_id, row.razorpay_customer_id) if row is not None else None

    async def insert_customer(self, user_id: UUID, razorpay_customer_id: str) -> None:
        await self.session.execute(
            pg_insert(BillingCustomer)
            .values(user_id=user_id, razorpay_customer_id=razorpay_customer_id)
            .on_conflict_do_nothing()
        )

    async def order_for_key(self, user_id: UUID, key: str) -> OrderRecord | None:
        row = await self.session.scalar(
            select(Order).where(Order.user_id == user_id, Order.idempotency_key == key).execution_options(**FRESH_ROWS)
        )
        return order_record(row) if row is not None else None

    async def insert_order(self, order: NewOrder) -> OrderRecord | None:
        inserted = await self.session.scalar(
            pg_insert(Order)
            .values(
                id=order.id,
                user_id=order.user_id,
                product_id=order.product.id,
                product_version=order.product.version,
                kind=order.product.kind,
                amount_paise=order.product.price_paise,
                currency=order.product.currency,
                credits_granted=order.product.credits_granted,
                status=OrderStatus.CREATED.value,
                subscription_id=order.subscription_id,
                receipt=str(order.id),
                idempotency_key=order.idempotency_key,
                expires_at=order.expires_at,
            )
            .on_conflict_do_nothing(constraint=ORDER_IDEMPOTENCY_CONSTRAINT)
            .returning(Order.id)
        )
        if inserted is None:
            return None
        return await self._order(inserted)

    async def _order(self, order_id: UUID) -> OrderRecord | None:
        row = await self.session.scalar(select(Order).where(Order.id == order_id).execution_options(**FRESH_ROWS))
        return order_record(row) if row is not None else None

    async def order_view(self, order_id: UUID, user_id: UUID) -> OrderView | None:
        row = (
            await self.session.execute(
                select(Order, Product.code, Product.name)
                .join(Product, Product.id == Order.product_id)
                .where(Order.id == order_id, Order.user_id == user_id)
                .execution_options(**FRESH_ROWS)
            )
        ).one_or_none()
        if row is None:
            return None
        return OrderView(order=order_record(row[0]), product_code=row[1], product_name=row[2])

    async def lock_order(self, order_id: UUID) -> OrderRecord | None:
        row = await self.session.scalar(
            select(Order).where(Order.id == order_id).with_for_update().execution_options(**FRESH_ROWS)
        )
        return order_record(row) if row is not None else None

    async def lock_order_by_razorpay_id(self, razorpay_order_id: str) -> OrderRecord | None:
        row = await self.session.scalar(
            select(Order)
            .where(Order.razorpay_order_id == razorpay_order_id)
            .with_for_update()
            .execution_options(**FRESH_ROWS)
        )
        return order_record(row) if row is not None else None

    async def order_by_razorpay_id_for_user(self, razorpay_order_id: str, user_id: UUID) -> OrderRecord | None:
        row = await self.session.scalar(
            select(Order)
            .where(Order.razorpay_order_id == razorpay_order_id, Order.user_id == user_id)
            .execution_options(**FRESH_ROWS)
        )
        return order_record(row) if row is not None else None

    async def transition_order(
        self, order_id: UUID, expected: OrderStatus, target: OrderStatus, values: Mapping[str, object]
    ) -> bool:
        changed = await self.session.scalar(
            update(Order)
            .where(Order.id == order_id, Order.status == expected.value)
            .values(status=target.value, **values)
            .returning(Order.id)
        )
        return changed is not None

    async def flag_order(self, order_id: UUID, reason: str, at: datetime) -> bool:
        changed = await self.session.scalar(
            update(Order)
            .where(Order.id == order_id, Order.flagged_at.is_(None))
            .values(flagged_at=at, flag_reason=reason)
            .returning(Order.id)
        )
        return changed is not None

    async def reconcilable_orders(self, before: datetime, after: Cursor | None, limit: int) -> list[OrderRecord]:
        statement = select(Order).where(
            Order.status.in_(RECONCILABLE_STATUSES), Order.flagged_at.is_(None), Order.created_at < before
        )
        if after is not None:
            statement = statement.where(tuple_(Order.created_at, Order.id) > tuple_(after.created_at, after.id))
        rows = await self.session.scalars(
            statement.order_by(Order.created_at, Order.id).limit(limit).execution_options(**FRESH_ROWS)
        )
        return [order_record(row) for row in rows]

    async def payment_by_razorpay_id(self, razorpay_payment_id: str) -> PaymentRecord | None:
        row = await self.session.scalar(
            select(Payment).where(Payment.razorpay_payment_id == razorpay_payment_id).execution_options(**FRESH_ROWS)
        )
        return payment_record(row) if row is not None else None

    async def insert_payment(self, payment: NewPayment) -> PaymentRecord:
        row = Payment(
            id=payment.id,
            order_id=payment.order_id,
            subscription_id=payment.subscription_id,
            user_id=payment.user_id,
            razorpay_payment_id=payment.razorpay_payment_id,
            amount_paise=payment.amount_paise,
            currency=payment.currency,
            status=payment.status.value,
            method=payment.method,
            fee_paise=payment.fee_paise,
            tax_paise=payment.tax_paise,
            credits_granted=0,
            refunded_paise=0,
            error_code=payment.error_code,
            error_description=payment.error_description,
            captured_at=payment.captured_at,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return payment_record(row)

    async def transition_payment(
        self,
        payment_id: UUID,
        expected: PaymentRecordStatus,
        target: PaymentRecordStatus,
        values: Mapping[str, object],
    ) -> bool:
        changed = await self.session.scalar(
            update(Payment)
            .where(Payment.id == payment_id, Payment.status == expected.value)
            .values(status=target.value, **values)
            .returning(Payment.id)
        )
        return changed is not None

    async def set_payment_credits(self, payment_id: UUID, amount: int) -> None:
        await self.session.execute(update(Payment).where(Payment.id == payment_id).values(credits_granted=amount))

    async def insert_event(self, event: NewWebhookEvent) -> bool:
        inserted = await self.session.scalar(
            pg_insert(WebhookEventModel)
            .values(
                id=event.id,
                provider=event.provider,
                event_id=event.event_id,
                event_type=event.event_type,
                event_created_at=event.event_created_at,
                payload=event.payload,
                status=WebhookEventStatus.RECEIVED.value,
                attempts=0,
                received_at=event.received_at,
            )
            .on_conflict_do_nothing(constraint=EVENT_UNIQUE_CONSTRAINT)
            .returning(WebhookEventModel.id)
        )
        return inserted is not None

    async def event_by_provider_id(self, provider: str, event_id: str) -> WebhookEventRecord | None:
        row = await self.session.scalar(
            select(WebhookEventModel)
            .where(WebhookEventModel.provider == provider, WebhookEventModel.event_id == event_id)
            .execution_options(**FRESH_ROWS)
        )
        return event_record(row) if row is not None else None

    async def lock_event(self, event_row_id: UUID) -> WebhookEventRecord | None:
        row = await self.session.scalar(
            select(WebhookEventModel)
            .where(WebhookEventModel.id == event_row_id)
            .with_for_update()
            .execution_options(**FRESH_ROWS)
        )
        return event_record(row) if row is not None else None

    async def transition_event(
        self,
        event_row_id: UUID,
        expected: WebhookEventStatus,
        target: WebhookEventStatus,
        values: Mapping[str, object],
    ) -> bool:
        changed = await self.session.scalar(
            update(WebhookEventModel)
            .where(WebhookEventModel.id == event_row_id, WebhookEventModel.status == expected.value)
            .values(status=target.value, **values)
            .returning(WebhookEventModel.id)
        )
        return changed is not None

    async def requeue_candidates(self, query: RequeueQuery) -> list[UUID]:
        result = await self.session.execute(
            REQUEUE_CANDIDATES,
            {
                "provider": query.provider,
                "stale_before": query.stale_before,
                "max_attempts": query.max_attempts,
                "task_name": query.task_name,
                "limit": query.limit,
            },
        )
        return [row[0] for row in result]

    async def start_run(self, run_id: UUID, run_type: str, now: datetime) -> None:
        self.session.add(ReconciliationRun(id=run_id, type=run_type, status=RunStatus.RUNNING.value, started_at=now))
        await self.session.flush()

    async def finish_run(self, run_id: UUID, outcome: RunOutcome) -> bool:
        changed = await self.session.scalar(
            update(ReconciliationRun)
            .where(ReconciliationRun.id == run_id, ReconciliationRun.status == RunStatus.RUNNING.value)
            .values(
                status=outcome.status.value,
                checked_count=outcome.counts.checked,
                repaired_count=outcome.counts.repaired,
                mismatch_count=outcome.counts.mismatch,
                summary=outcome.summary,
                report_storage_key=outcome.report_storage_key,
                error=outcome.error[:ERROR_LIMIT] if outcome.error is not None else None,
                finished_at=outcome.finished_at,
            )
            .returning(ReconciliationRun.id)
        )
        return changed is not None

    async def product_by_plan_id(self, razorpay_plan_id: str) -> ProductRecord | None:
        row = await self.session.scalar(
            select(Product).where(Product.razorpay_plan_id == razorpay_plan_id).execution_options(**FRESH_ROWS)
        )
        return product_record(row) if row is not None else None

    async def insert_subscription(self, subscription: NewSubscription) -> SubscriptionRecord:
        row = Subscription(
            id=subscription.id,
            user_id=subscription.user_id,
            product_id=subscription.product_id,
            status=SubscriptionStatus.CREATED.value,
            total_count=subscription.total_count,
            paid_count=0,
            cancel_at_period_end=False,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return subscription_record(row)

    async def _subscription(self, *conditions: ColumnElement[bool], lock: bool = False) -> SubscriptionRecord | None:
        statement = select(Subscription).where(*conditions).execution_options(**FRESH_ROWS)
        row = await self.session.scalar(statement.with_for_update() if lock else statement)
        return subscription_record(row) if row is not None else None

    async def subscription_for_user(self, subscription_id: UUID, user_id: UUID) -> SubscriptionRecord | None:
        return await self._subscription(Subscription.id == subscription_id, Subscription.user_id == user_id)

    async def lock_subscription_for_user(self, subscription_id: UUID, user_id: UUID) -> SubscriptionRecord | None:
        return await self._subscription(Subscription.id == subscription_id, Subscription.user_id == user_id, lock=True)

    async def lock_subscription(self, subscription_id: UUID) -> SubscriptionRecord | None:
        return await self._subscription(Subscription.id == subscription_id, lock=True)

    async def lock_subscription_by_razorpay_id(self, razorpay_subscription_id: str) -> SubscriptionRecord | None:
        return await self._subscription(Subscription.razorpay_subscription_id == razorpay_subscription_id, lock=True)

    async def lock_subscription_by_razorpay_id_for_user(
        self, razorpay_subscription_id: str, user_id: UUID
    ) -> SubscriptionRecord | None:
        return await self._subscription(
            Subscription.razorpay_subscription_id == razorpay_subscription_id,
            Subscription.user_id == user_id,
            lock=True,
        )

    async def live_subscription(self, user_id: UUID) -> SubscriptionRecord | None:
        return await self._subscription(Subscription.user_id == user_id, Subscription.status.in_(LIVE_STATUS_VALUES))

    async def lock_live_subscription(self, user_id: UUID) -> SubscriptionRecord | None:
        return await self._subscription(
            Subscription.user_id == user_id, Subscription.status.in_(LIVE_STATUS_VALUES), lock=True
        )

    async def transition_subscription(
        self,
        subscription_id: UUID,
        expected: SubscriptionStatus,
        target: SubscriptionStatus,
        values: Mapping[str, object],
    ) -> bool:
        statement = (
            update(Subscription)
            .where(Subscription.id == subscription_id, Subscription.status == expected.value)
            .values(status=target.value, **values)
            .returning(Subscription.id)
        )
        try:
            async with self.session.begin_nested():
                changed = await self.session.scalar(statement)
        except IntegrityError as error:
            if LIVE_SUBSCRIPTION_INDEX in str(error.orig):
                raise LiveSubscriptionConflictError from error
            raise
        return changed is not None

    async def update_subscription(self, subscription_id: UUID, values: Mapping[str, object]) -> None:
        await self.session.execute(update(Subscription).where(Subscription.id == subscription_id).values(**values))

    async def lock_subscription_order(self, subscription_id: UUID) -> OrderRecord | None:
        row = await self.session.scalar(
            select(Order)
            .where(Order.subscription_id == subscription_id)
            .order_by(Order.created_at, Order.id)
            .limit(1)
            .with_for_update()
            .execution_options(**FRESH_ROWS)
        )
        return order_record(row) if row is not None else None

    async def subscription_payment_count(self, subscription_id: UUID) -> int:
        count = await self.session.scalar(
            select(func.count()).select_from(Payment).where(Payment.subscription_id == subscription_id)
        )
        return count or 0

    async def due_cancellations(self, now: datetime, after: UUID | None, limit: int) -> list[SubscriptionRecord]:
        statement = select(Subscription).where(
            Subscription.status.in_(LIVE_STATUS_VALUES),
            Subscription.cancel_at_period_end.is_(True),
            Subscription.current_period_end <= now,
        )
        return await self._subscription_page(statement, after, limit)

    async def abandoned_subscriptions(self, now: datetime, after: UUID | None, limit: int) -> list[SubscriptionRecord]:
        statement = select(Subscription).where(
            Subscription.status == SubscriptionStatus.CREATED.value,
            Subscription.last_event_at.is_(None),
            select(Order.id).where(Order.subscription_id == Subscription.id, Order.expires_at <= now).exists(),
        )
        return await self._subscription_page(statement, after, limit)

    async def live_subscriptions(self, after: UUID | None, limit: int) -> list[SubscriptionRecord]:
        statement = select(Subscription).where(Subscription.status.in_(LIVE_STATUS_VALUES))
        return await self._subscription_page(statement, after, limit)

    async def unactivated_subscriptions(self, after: UUID | None, limit: int) -> list[SubscriptionRecord]:
        statement = select(Subscription).where(
            Subscription.status == SubscriptionStatus.CREATED.value, Subscription.razorpay_subscription_id.is_not(None)
        )
        return await self._subscription_page(statement, after, limit)

    async def _subscription_page(
        self, statement: Select[Subscription], after: UUID | None, limit: int
    ) -> list[SubscriptionRecord]:
        if after is not None:
            statement = statement.where(Subscription.id > after)
        rows = await self.session.scalars(
            statement.order_by(Subscription.id).limit(limit).execution_options(**FRESH_ROWS)
        )
        return [subscription_record(row) for row in rows]

    async def payment_by_id(self, payment_id: UUID) -> PaymentRecord | None:
        row = await self.session.scalar(select(Payment).where(Payment.id == payment_id).execution_options(**FRESH_ROWS))
        return payment_record(row) if row is not None else None

    async def lock_payment(self, payment_id: UUID) -> PaymentRecord | None:
        row = await self.session.scalar(
            select(Payment).where(Payment.id == payment_id).with_for_update().execution_options(**FRESH_ROWS)
        )
        return payment_record(row) if row is not None else None

    async def captured_payments_between(
        self, start: datetime, end: datetime, after: UUID | None, limit: int
    ) -> list[PaymentRecord]:
        statement = select(Payment).where(
            Payment.status.in_(CAPTURED_FAMILY_VALUES), Payment.created_at >= start, Payment.created_at < end
        )
        if after is not None:
            statement = statement.where(Payment.id > after)
        rows = await self.session.scalars(statement.order_by(Payment.id).limit(limit).execution_options(**FRESH_ROWS))
        return [payment_record(row) for row in rows]

    async def pending_refund_totals(self, payment_ids: Sequence[UUID]) -> dict[UUID, int]:
        if not payment_ids:
            return {}
        rows = await self.session.execute(
            select(Refund.payment_id, func.coalesce(func.sum(Refund.amount_paise), 0))
            .where(Refund.payment_id.in_(payment_ids), Refund.status == RefundStatus.PENDING.value)
            .group_by(Refund.payment_id)
        )
        return {row[0]: int(row[1]) for row in rows}

    async def clawed_back_total(self, payment_id: UUID) -> int:
        total = await self.session.scalar(
            select(func.coalesce(func.sum(Refund.credits_clawed_back), 0)).where(
                Refund.payment_id == payment_id, Refund.status == RefundStatus.PROCESSED.value
            )
        )
        return int(total or 0)

    async def insert_refund(self, refund: NewRefund) -> RefundRecord:
        row = Refund(
            id=refund.id,
            payment_id=refund.payment_id,
            amount_paise=refund.amount_paise,
            status=RefundStatus.PENDING.value,
            reason=refund.reason,
            initiated_by=refund.initiated_by,
            credits_clawed_back=0,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return refund_record(row)

    async def refund_by_id(self, refund_id: UUID) -> RefundRecord | None:
        row = await self.session.scalar(select(Refund).where(Refund.id == refund_id).execution_options(**FRESH_ROWS))
        return refund_record(row) if row is not None else None

    async def refund_by_razorpay_id(self, razorpay_refund_id: str) -> RefundRecord | None:
        row = await self.session.scalar(
            select(Refund).where(Refund.razorpay_refund_id == razorpay_refund_id).execution_options(**FRESH_ROWS)
        )
        return refund_record(row) if row is not None else None

    async def lock_refund(self, refund_id: UUID) -> RefundRecord | None:
        row = await self.session.scalar(
            select(Refund).where(Refund.id == refund_id).with_for_update().execution_options(**FRESH_ROWS)
        )
        return refund_record(row) if row is not None else None

    async def transition_refund(
        self, refund_id: UUID, expected: RefundStatus, target: RefundStatus, values: Mapping[str, object]
    ) -> bool:
        changed = await self.session.scalar(
            update(Refund)
            .where(Refund.id == refund_id, Refund.status == expected.value)
            .values(status=target.value, **values)
            .returning(Refund.id)
        )
        return changed is not None

    async def update_refund(self, refund_id: UUID, values: Mapping[str, object]) -> None:
        await self.session.execute(update(Refund).where(Refund.id == refund_id).values(**values))

    async def claim_settlement_run(
        self, period_start: datetime, period_end: datetime, now: datetime, stale_before: datetime
    ) -> RunClaim | None:
        inserted = await self.session.scalar(
            pg_insert(ReconciliationRun)
            .values(
                id=new_id(),
                type=SETTLEMENT_RUN_TYPE,
                period_start=period_start,
                period_end=period_end,
                status=RunStatus.RUNNING.value,
                started_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=[ReconciliationRun.period_start],
                index_where=ReconciliationRun.type == SETTLEMENT_RUN_TYPE,
            )
            .returning(ReconciliationRun.id)
        )
        if inserted is not None:
            return RunClaim(inserted, resumed=False)
        existing = await self.session.scalar(
            select(ReconciliationRun)
            .where(ReconciliationRun.type == SETTLEMENT_RUN_TYPE, ReconciliationRun.period_start == period_start)
            .with_for_update()
            .execution_options(**FRESH_ROWS)
        )
        if existing is None:
            return None
        restart: dict[str, object] = {
            "started_at": now,
            "finished_at": None,
            "error": None,
            "summary": {},
            "checked_count": 0,
            "repaired_count": 0,
            "mismatch_count": 0,
            "report_storage_key": None,
        }
        if existing.status == RunStatus.FAILED.value:
            RUN_MACHINE.require(RunStatus.FAILED, RunStatus.RUNNING)
            return await self._restart_run(
                existing.id, RunStatus.FAILED, {"status": RunStatus.RUNNING.value, **restart}
            )
        if existing.status == RunStatus.RUNNING.value and existing.started_at < stale_before:
            return await self._restart_run(existing.id, RunStatus.RUNNING, restart)
        return None

    async def _restart_run(self, run_id: UUID, expected: RunStatus, values: Mapping[str, object]) -> RunClaim | None:
        changed = await self.session.scalar(
            update(ReconciliationRun)
            .where(ReconciliationRun.id == run_id, ReconciliationRun.status == expected.value)
            .values(**values)
            .returning(ReconciliationRun.id)
        )
        return RunClaim(changed, resumed=True) if changed is not None else None

    async def history(self, user_id: UUID, cursor: Cursor | None, limit: int) -> list[HistoryRow]:
        orders = (
            select(
                literal("order", String).label("kind"),
                Order.id.label("id"),
                Order.status.label("status"),
                Order.amount_paise.label("amount_paise"),
                Order.currency.label("currency"),
                Product.name.label("title"),
                Order.credits_granted.label("credits_granted"),
                Order.created_at.label("created_at"),
                Order.id.label("order_id"),
                cast(null(), PG_UUID(as_uuid=True)).label("payment_id"),
            )
            .join(Product, Product.id == Order.product_id)
            .where(Order.user_id == user_id, Order.status != HIDDEN_HISTORY_STATUS)
        )
        payments = (
            select(
                literal("payment", String).label("kind"),
                Payment.id.label("id"),
                Payment.status.label("status"),
                Payment.amount_paise.label("amount_paise"),
                Payment.currency.label("currency"),
                func.concat(PAYMENT_TITLE_PREFIX, func.coalesce(Product.name, FALLBACK_SUBJECT)).label("title"),
                Payment.credits_granted.label("credits_granted"),
                Payment.created_at.label("created_at"),
                Payment.order_id.label("order_id"),
                Payment.id.label("payment_id"),
            )
            .select_from(Payment)
            .outerjoin(Order, Order.id == Payment.order_id)
            .outerjoin(Product, Product.id == Order.product_id)
            .where(Payment.user_id == user_id)
        )
        refunds = (
            select(
                literal("refund", String).label("kind"),
                Refund.id.label("id"),
                Refund.status.label("status"),
                Refund.amount_paise.label("amount_paise"),
                Payment.currency.label("currency"),
                func.concat(REFUND_TITLE_PREFIX, func.coalesce(Product.name, FALLBACK_SUBJECT)).label("title"),
                cast(null(), BigInteger).label("credits_granted"),
                Refund.created_at.label("created_at"),
                Payment.order_id.label("order_id"),
                Payment.id.label("payment_id"),
            )
            .select_from(Refund)
            .join(Payment, Payment.id == Refund.payment_id)
            .outerjoin(Order, Order.id == Payment.order_id)
            .outerjoin(Product, Product.id == Order.product_id)
            .where(Payment.user_id == user_id)
        )
        timeline = union_all(orders, payments, refunds).subquery("timeline")
        statement = keyset_page(
            select(timeline), created_at=timeline.c.created_at, id_=timeline.c.id, cursor=cursor, limit=limit
        )
        rows = (await self.session.execute(statement)).mappings().all()
        return [history_row(row) for row in rows]


def history_row(values: RowMapping) -> HistoryRow:
    kind: HistoryKind = values["kind"]
    return HistoryRow(
        kind=kind,
        id=values["id"],
        status=values["status"],
        amount_paise=values["amount_paise"],
        currency=values["currency"],
        title=values["title"],
        credits_granted=values["credits_granted"],
        created_at=values["created_at"],
        order_id=values["order_id"],
        payment_id=values["payment_id"],
    )
