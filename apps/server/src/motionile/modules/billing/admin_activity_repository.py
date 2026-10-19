from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, defer

from motionile.core.pagination import Cursor, keyset_page
from motionile.modules.billing.admin_records import (
    EventDetail,
    EventFilter,
    EventSummary,
    OrderFilter,
    OrderRow,
    PaymentFilter,
    PaymentRow,
    RefundFilter,
    RefundRow,
    RunFilter,
    RunRow,
    SubscriptionFilter,
    SubscriptionRow,
)
from motionile.modules.billing.models import (
    Order,
    Payment,
    Product,
    ReconciliationRun,
    Refund,
    Subscription,
)
from motionile.modules.billing.models import WebhookEvent as WebhookEventModel
from motionile.modules.billing.records import RefundRecord
from motionile.modules.billing.repository import (
    FRESH_ROWS,
    event_record,
    order_record,
    payment_record,
    product_record,
    refund_record,
    subscription_record,
)
from motionile.modules.billing.states import RefundStatus, RunStatus, WebhookEventStatus
from motionile.modules.users import User


class BillingActivityStore(Protocol):
    async def user_exists(self, user_id: UUID) -> bool: ...
    async def list_payments(self, query: PaymentFilter, cursor: Cursor | None, limit: int) -> list[PaymentRow]: ...
    async def payment_row(self, payment_id: UUID) -> PaymentRow | None: ...
    async def payments_for_order(self, order_id: UUID) -> list[PaymentRow]: ...
    async def payments_for_subscription(self, subscription_id: UUID) -> list[PaymentRow]: ...
    async def refunds_for_payment(self, payment_id: UUID) -> list[RefundRecord]: ...
    async def pending_refund_total(self, payment_id: UUID) -> int: ...
    async def clawed_back_total(self, payment_id: UUID) -> int: ...
    async def list_orders(self, query: OrderFilter, cursor: Cursor | None, limit: int) -> list[OrderRow]: ...
    async def order_row(self, order_id: UUID) -> OrderRow | None: ...
    async def orders_for_subscription(self, subscription_id: UUID) -> list[OrderRow]: ...
    async def list_refunds(self, query: RefundFilter, cursor: Cursor | None, limit: int) -> list[RefundRow]: ...
    async def refund_row(self, refund_id: UUID) -> RefundRow | None: ...
    async def list_subscriptions(
        self, query: SubscriptionFilter, cursor: Cursor | None, limit: int
    ) -> list[SubscriptionRow]: ...
    async def subscription_row(self, subscription_id: UUID) -> SubscriptionRow | None: ...
    async def list_events(self, query: EventFilter, cursor: Cursor | None, limit: int) -> list[EventSummary]: ...
    async def event_detail(self, event_row_id: UUID) -> EventDetail | None: ...
    async def list_runs(self, query: RunFilter, cursor: Cursor | None, limit: int) -> list[RunRow]: ...
    async def run_row(self, run_id: UUID) -> RunRow | None: ...


def payments_statement() -> Select[Payment, str, str, datetime | None]:
    product_id = func.coalesce(Order.product_id, Subscription.product_id)
    return (
        select(Payment, Product.code, Product.name, Order.flagged_at)
        .select_from(Payment)
        .outerjoin(Order, Order.id == Payment.order_id)
        .outerjoin(Subscription, Subscription.id == Payment.subscription_id)
        .outerjoin(Product, Product.id == product_id)
    )


def payment_row(values: tuple[Payment, str | None, str | None, datetime | None]) -> PaymentRow:
    return PaymentRow(
        payment=payment_record(values[0]),
        product_code=values[1],
        product_name=values[2],
        flagged=values[3] is not None,
    )


def payment_conditions(query: PaymentFilter) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if query.status is not None:
        conditions.append(Payment.status == query.status.value)
    if query.user_id is not None:
        conditions.append(Payment.user_id == query.user_id)
    if query.order_id is not None:
        conditions.append(Payment.order_id == query.order_id)
    if query.created_from is not None:
        conditions.append(Payment.created_at >= query.created_from)
    if query.created_to is not None:
        conditions.append(Payment.created_at < query.created_to)
    if query.flagged is True:
        conditions.append(Order.flagged_at.is_not(None))
    if query.flagged is False:
        conditions.append(Order.flagged_at.is_(None))
    return conditions


def order_row_of(values: tuple[Order, str, str]) -> OrderRow:
    return OrderRow(order=order_record(values[0]), product_code=values[1], product_name=values[2])


def order_conditions(query: OrderFilter) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if query.status is not None:
        conditions.append(Order.status == query.status.value)
    if query.user_id is not None:
        conditions.append(Order.user_id == query.user_id)
    if query.flagged is True:
        conditions.append(Order.flagged_at.is_not(None))
    if query.flagged is False:
        conditions.append(Order.flagged_at.is_(None))
    return conditions


def refund_row_of(values: tuple[Refund, UUID, int, str]) -> RefundRow:
    return RefundRow(
        refund=refund_record(values[0]), user_id=values[1], payment_amount_paise=values[2], currency=values[3]
    )


def subscription_row_of(values: tuple[Subscription, Product, Product | None]) -> SubscriptionRow:
    return SubscriptionRow(
        subscription=subscription_record(values[0]),
        product=product_record(values[1]),
        pending_product=product_record(values[2]) if values[2] is not None else None,
    )


def event_summary(model: WebhookEventModel) -> EventSummary:
    return EventSummary(
        id=model.id,
        provider=model.provider,
        event_id=model.event_id,
        event_type=model.event_type,
        event_created_at=model.event_created_at,
        status=WebhookEventStatus(model.status),
        attempts=model.attempts,
        last_error=model.last_error,
        ignored_reason=model.ignored_reason,
        received_at=model.received_at,
        processed_at=model.processed_at,
        created_at=model.created_at,
    )


def run_row_of(model: ReconciliationRun) -> RunRow:
    return RunRow(
        id=model.id,
        type=model.type,
        status=RunStatus(model.status),
        period_start=model.period_start,
        period_end=model.period_end,
        checked_count=model.checked_count,
        repaired_count=model.repaired_count,
        mismatch_count=model.mismatch_count,
        summary=dict(model.summary),
        report_storage_key=model.report_storage_key,
        error=model.error,
        started_at=model.started_at,
        finished_at=model.finished_at,
        created_at=model.created_at,
    )


class SqlBillingActivityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def user_exists(self, user_id: UUID) -> bool:
        return await self.session.scalar(select(User.id).where(User.id == user_id)) is not None

    async def list_payments(self, query: PaymentFilter, cursor: Cursor | None, limit: int) -> list[PaymentRow]:
        statement = keyset_page(
            payments_statement().where(*payment_conditions(query)),
            created_at=Payment.created_at,
            id_=Payment.id,
            cursor=cursor,
            limit=limit,
        ).execution_options(**FRESH_ROWS)
        return [payment_row(row) for row in (await self.session.execute(statement))]

    async def payment_row(self, payment_id: UUID) -> PaymentRow | None:
        row = (
            await self.session.execute(
                payments_statement().where(Payment.id == payment_id).execution_options(**FRESH_ROWS)
            )
        ).one_or_none()
        return payment_row(row) if row is not None else None

    async def payments_for_order(self, order_id: UUID) -> list[PaymentRow]:
        statement = (
            payments_statement().where(Payment.order_id == order_id).order_by(Payment.created_at, Payment.id)
        ).execution_options(**FRESH_ROWS)
        return [payment_row(row) for row in (await self.session.execute(statement))]

    async def payments_for_subscription(self, subscription_id: UUID) -> list[PaymentRow]:
        statement = (
            payments_statement()
            .where(Payment.subscription_id == subscription_id)
            .order_by(Payment.created_at.desc(), Payment.id.desc())
        ).execution_options(**FRESH_ROWS)
        return [payment_row(row) for row in (await self.session.execute(statement))]

    async def refunds_for_payment(self, payment_id: UUID) -> list[RefundRecord]:
        rows = await self.session.scalars(
            select(Refund)
            .where(Refund.payment_id == payment_id)
            .order_by(Refund.created_at, Refund.id)
            .execution_options(**FRESH_ROWS)
        )
        return [refund_record(row) for row in rows]

    async def pending_refund_total(self, payment_id: UUID) -> int:
        total = await self.session.scalar(
            select(func.coalesce(func.sum(Refund.amount_paise), 0)).where(
                Refund.payment_id == payment_id, Refund.status == RefundStatus.PENDING.value
            )
        )
        return int(total or 0)

    async def clawed_back_total(self, payment_id: UUID) -> int:
        total = await self.session.scalar(
            select(func.coalesce(func.sum(Refund.credits_clawed_back), 0)).where(
                Refund.payment_id == payment_id, Refund.status == RefundStatus.PROCESSED.value
            )
        )
        return int(total or 0)

    async def list_orders(self, query: OrderFilter, cursor: Cursor | None, limit: int) -> list[OrderRow]:
        statement = keyset_page(
            select(Order, Product.code, Product.name)
            .join(Product, Product.id == Order.product_id)
            .where(*order_conditions(query)),
            created_at=Order.created_at,
            id_=Order.id,
            cursor=cursor,
            limit=limit,
        ).execution_options(**FRESH_ROWS)
        return [order_row_of(row) for row in (await self.session.execute(statement))]

    async def order_row(self, order_id: UUID) -> OrderRow | None:
        row = (
            await self.session.execute(
                select(Order, Product.code, Product.name)
                .join(Product, Product.id == Order.product_id)
                .where(Order.id == order_id)
                .execution_options(**FRESH_ROWS)
            )
        ).one_or_none()
        return order_row_of(row) if row is not None else None

    async def orders_for_subscription(self, subscription_id: UUID) -> list[OrderRow]:
        rows = await self.session.execute(
            select(Order, Product.code, Product.name)
            .join(Product, Product.id == Order.product_id)
            .where(Order.subscription_id == subscription_id)
            .order_by(Order.created_at.desc(), Order.id.desc())
            .execution_options(**FRESH_ROWS)
        )
        return [order_row_of(row) for row in rows]

    async def list_refunds(self, query: RefundFilter, cursor: Cursor | None, limit: int) -> list[RefundRow]:
        statement = select(Refund, Payment.user_id, Payment.amount_paise, Payment.currency).join(
            Payment, Payment.id == Refund.payment_id
        )
        if query.status is not None:
            statement = statement.where(Refund.status == query.status.value)
        if query.payment_id is not None:
            statement = statement.where(Refund.payment_id == query.payment_id)
        paged = keyset_page(
            statement, created_at=Refund.created_at, id_=Refund.id, cursor=cursor, limit=limit
        ).execution_options(**FRESH_ROWS)
        return [refund_row_of(row) for row in (await self.session.execute(paged))]

    async def refund_row(self, refund_id: UUID) -> RefundRow | None:
        row = (
            await self.session.execute(
                select(Refund, Payment.user_id, Payment.amount_paise, Payment.currency)
                .join(Payment, Payment.id == Refund.payment_id)
                .where(Refund.id == refund_id)
                .execution_options(**FRESH_ROWS)
            )
        ).one_or_none()
        return refund_row_of(row) if row is not None else None

    async def list_subscriptions(
        self, query: SubscriptionFilter, cursor: Cursor | None, limit: int
    ) -> list[SubscriptionRow]:
        pending = aliased(Product)
        statement = (
            select(Subscription, Product, pending)
            .join(Product, Product.id == Subscription.product_id)
            .outerjoin(pending, pending.id == Subscription.pending_product_id)
        )
        if query.status is not None:
            statement = statement.where(Subscription.status == query.status.value)
        if query.product_id is not None:
            statement = statement.where(Subscription.product_id == query.product_id)
        if query.plan_key is not None:
            statement = statement.where(Product.plan_key == query.plan_key)
        if query.user_id is not None:
            statement = statement.where(Subscription.user_id == query.user_id)
        paged = keyset_page(
            statement, created_at=Subscription.created_at, id_=Subscription.id, cursor=cursor, limit=limit
        ).execution_options(**FRESH_ROWS)
        return [subscription_row_of(row) for row in (await self.session.execute(paged))]

    async def subscription_row(self, subscription_id: UUID) -> SubscriptionRow | None:
        pending = aliased(Product)
        row = (
            await self.session.execute(
                select(Subscription, Product, pending)
                .join(Product, Product.id == Subscription.product_id)
                .outerjoin(pending, pending.id == Subscription.pending_product_id)
                .where(Subscription.id == subscription_id)
                .execution_options(**FRESH_ROWS)
            )
        ).one_or_none()
        return subscription_row_of(row) if row is not None else None

    async def list_events(self, query: EventFilter, cursor: Cursor | None, limit: int) -> list[EventSummary]:
        statement = select(WebhookEventModel).options(defer(WebhookEventModel.payload))
        if query.status is not None:
            statement = statement.where(WebhookEventModel.status == query.status.value)
        if query.event_type is not None:
            statement = statement.where(WebhookEventModel.event_type == query.event_type)
        if query.received_from is not None:
            statement = statement.where(WebhookEventModel.received_at >= query.received_from)
        if query.received_to is not None:
            statement = statement.where(WebhookEventModel.received_at < query.received_to)
        paged = keyset_page(
            statement,
            created_at=WebhookEventModel.created_at,
            id_=WebhookEventModel.id,
            cursor=cursor,
            limit=limit,
        ).execution_options(**FRESH_ROWS)
        return [event_summary(model) for model in await self.session.scalars(paged)]

    async def event_detail(self, event_row_id: UUID) -> EventDetail | None:
        model = await self.session.scalar(
            select(WebhookEventModel).where(WebhookEventModel.id == event_row_id).execution_options(**FRESH_ROWS)
        )
        if model is None:
            return None
        return EventDetail(summary=event_summary(model), payload=event_record(model).payload)

    async def list_runs(self, query: RunFilter, cursor: Cursor | None, limit: int) -> list[RunRow]:
        statement = select(ReconciliationRun)
        if query.type is not None:
            statement = statement.where(ReconciliationRun.type == query.type)
        if query.status is not None:
            statement = statement.where(ReconciliationRun.status == query.status.value)
        if query.has_mismatches is True:
            statement = statement.where(ReconciliationRun.mismatch_count > 0)
        if query.has_mismatches is False:
            statement = statement.where(ReconciliationRun.mismatch_count == 0)
        paged = keyset_page(
            statement, created_at=ReconciliationRun.created_at, id_=ReconciliationRun.id, cursor=cursor, limit=limit
        ).execution_options(**FRESH_ROWS)
        return [run_row_of(model) for model in await self.session.scalars(paged)]

    async def run_row(self, run_id: UUID) -> RunRow | None:
        model = await self.session.scalar(
            select(ReconciliationRun).where(ReconciliationRun.id == run_id).execution_options(**FRESH_ROWS)
        )
        return run_row_of(model) if model is not None else None
