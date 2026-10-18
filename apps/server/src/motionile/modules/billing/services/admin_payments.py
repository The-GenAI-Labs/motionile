from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.pagination import CursorCodec
from motionile.modules.billing.admin_activity_repository import BillingActivityStore, SqlBillingActivityRepository
from motionile.modules.billing.admin_records import (
    OrderFilter,
    OrderRow,
    PaymentDetail,
    PaymentFilter,
    PaymentRow,
    RecordPage,
    RefundFilter,
    RefundRow,
)
from motionile.modules.billing.exceptions import OrderNotFoundError, PaymentNotFoundError, RefundNotFoundError
from motionile.modules.billing.ports import Transaction
from motionile.modules.billing.services.admin_paging import decode_cursor, record_page
from motionile.modules.billing.services.refund_rules import (
    REFUNDABLE_PAYMENT_STATUSES,
    clawback_amount,
    refundable_paise,
    resolve_refund_amount,
)
from motionile.modules.credits import CreditRef, LotRecord, lot_for_reference

type ActivityStoreOf = Callable[[AsyncSession], BillingActivityStore]
type LotLookup = Callable[[AsyncSession, CreditRef], Awaitable[LotRecord | None]]


class PaymentAdminService:
    def __init__(
        self,
        transaction: Transaction,
        codec: CursorCodec,
        *,
        store_factory: ActivityStoreOf = SqlBillingActivityRepository,
        lot_lookup: LotLookup = lot_for_reference,
    ) -> None:
        self._transaction = transaction
        self._codec = codec
        self._store_factory = store_factory
        self._lot_lookup = lot_lookup

    async def list_payments(self, query: PaymentFilter, cursor: str | None, limit: int) -> RecordPage[PaymentRow]:
        position = decode_cursor(self._codec, cursor)
        async with self._transaction() as session:
            rows = await self._store_factory(session).list_payments(query, position, limit)
        return record_page(rows, limit, self._codec, lambda row: (row.payment.created_at, row.payment.id))

    async def payment(self, payment_id: UUID, preview_paise: int | None) -> PaymentDetail:
        async with self._transaction() as session:
            store = self._store_factory(session)
            row = await store.payment_row(payment_id)
            if row is None:
                raise PaymentNotFoundError
            payment = row.payment
            order = await store.order_row(payment.order_id) if payment.order_id is not None else None
            subscription_id = payment.subscription_id or (order.order.subscription_id if order is not None else None)
            subscription = await store.subscription_row(subscription_id) if subscription_id is not None else None
            refunds = await store.refunds_for_payment(payment_id)
            pending = await store.pending_refund_total(payment_id)
            clawed_back = await store.clawed_back_total(payment_id)
            lot = await self._lot_lookup(session, CreditRef("payment", payment_id))
        refundable = (
            refundable_paise(
                amount_paise=payment.amount_paise, refunded_paise=payment.refunded_paise, pending_paise=pending
            )
            if payment.status in REFUNDABLE_PAYMENT_STATUSES
            else 0
        )
        wants_preview = preview_paise is not None or refundable > 0
        previewed = resolve_refund_amount(preview_paise, refundable) if wants_preview else 0
        return PaymentDetail(
            row=row,
            order=order,
            subscription=subscription,
            refunds=refunds,
            lot=lot,
            refundable_paise=refundable,
            pending_refund_paise=pending,
            preview_amount_paise=previewed,
            credits_to_claw_back=clawback_amount(
                credits_granted=payment.credits_granted,
                payment_amount_paise=payment.amount_paise,
                refund_amount_paise=previewed,
                already_clawed_back=clawed_back,
                lot_remaining=lot.remaining if lot is not None else 0,
            ),
        )

    async def list_orders(self, query: OrderFilter, cursor: str | None, limit: int) -> RecordPage[OrderRow]:
        position = decode_cursor(self._codec, cursor)
        async with self._transaction() as session:
            rows = await self._store_factory(session).list_orders(query, position, limit)
        return record_page(rows, limit, self._codec, lambda row: (row.order.created_at, row.order.id))

    async def order(self, order_id: UUID) -> tuple[OrderRow, list[PaymentRow]]:
        async with self._transaction() as session:
            store = self._store_factory(session)
            row = await store.order_row(order_id)
            if row is None:
                raise OrderNotFoundError
            return row, await store.payments_for_order(order_id)

    async def list_refunds(self, query: RefundFilter, cursor: str | None, limit: int) -> RecordPage[RefundRow]:
        position = decode_cursor(self._codec, cursor)
        async with self._transaction() as session:
            rows = await self._store_factory(session).list_refunds(query, position, limit)
        return record_page(rows, limit, self._codec, lambda row: (row.refund.created_at, row.refund.id))

    async def refund(self, refund_id: UUID) -> RefundRow:
        async with self._transaction() as session:
            row = await self._store_factory(session).refund_row(refund_id)
        if row is None:
            raise RefundNotFoundError
        return row
