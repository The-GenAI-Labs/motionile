from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from motionile.core.clock import Clock
from motionile.core.config import BillingSettings
from motionile.core.idempotency import IdempotencyKeyReusedError
from motionile.core.ids import new_id
from motionile.modules.billing.exceptions import (
    OrderNotFoundError,
    OrderNotPayableError,
    PaymentProviderError,
    PaymentProviderRejectedError,
    ProductNotFoundError,
    ProductNotPurchasableError,
)
from motionile.modules.billing.ports import StoreFactory, Transaction
from motionile.modules.billing.razorpay.api import RazorpayApi
from motionile.modules.billing.razorpay.exceptions import RazorpayApiError, RazorpayBadRequestError, RazorpayError
from motionile.modules.billing.razorpay.models import RazorpayOrder
from motionile.modules.billing.records import NewOrder, OrderRecord, OrderView, ProductRecord
from motionile.modules.billing.repository import SqlBillingRepository
from motionile.modules.billing.schemas import CheckoutResponse
from motionile.modules.billing.services.checkout import build_checkout
from motionile.modules.billing.services.customers import CustomerService
from motionile.modules.billing.services.provider import is_ambiguous, provider_error
from motionile.modules.billing.states import OrderStatus
from motionile.modules.billing.transitions import transition_order

CREDIT_PACK = "credit_pack"
FAILURE_REASON_LIMIT = 300
PAYABLE_STATUSES = frozenset({OrderStatus.CREATED, OrderStatus.PENDING})

type KeyIdSource = Callable[[], str]


@dataclass(frozen=True)
class PreparedOrder:
    order: OrderRecord
    product: ProductRecord
    retried: bool


def rejection_reason(error: RazorpayApiError) -> str:
    detail = ": ".join(part for part in (error.code, error.description) if part)
    return (detail or f"rejected with status {error.status_code}")[:FAILURE_REASON_LIMIT]


@dataclass(frozen=True)
class OrderDependencies:
    transaction: Transaction
    razorpay: RazorpayApi
    customers: CustomerService
    clock: Clock
    settings: BillingSettings
    key_id: KeyIdSource


class OrderService:
    def __init__(self, deps: OrderDependencies, *, store_factory: StoreFactory = SqlBillingRepository) -> None:
        self._transaction = deps.transaction
        self._razorpay = deps.razorpay
        self._customers = deps.customers
        self._clock = deps.clock
        self._settings = deps.settings
        self._key_id = deps.key_id
        self._store_factory = store_factory

    async def create(self, user_id: UUID, product_code: str, idempotency_key: str) -> CheckoutResponse:
        prepared = await self._prepare(user_id, product_code, idempotency_key)
        order = prepared.order
        if order.status not in PAYABLE_STATUSES:
            raise OrderNotPayableError("This order can no longer be paid. Start a new purchase.")
        customer = await self._customers.ensure(user_id)
        if order.status is OrderStatus.CREATED:
            order = await self._open_remote_order(prepared)
        return build_checkout(order=order, product_name=prepared.product.name, key_id=self._key_id(), customer=customer)

    async def get(self, user_id: UUID, order_id: UUID) -> OrderView:
        async with self._transaction() as session:
            view = await self._store_factory(session).order_view(order_id, user_id)
        if view is None:
            raise OrderNotFoundError
        return view

    async def _prepare(self, user_id: UUID, product_code: str, idempotency_key: str) -> PreparedOrder:
        async with self._transaction() as session:
            store = self._store_factory(session)
            existing = await store.order_for_key(user_id, idempotency_key)
            if existing is None:
                product = await store.share_product_by_code(product_code)
                if product is None or not product.is_active:
                    raise ProductNotFoundError
                if product.kind != CREDIT_PACK:
                    raise ProductNotPurchasableError
                expires_at = self._clock.now() + timedelta(seconds=self._settings.order_expiry_seconds)
                created = await store.insert_order(NewOrder(new_id(), user_id, product, idempotency_key, expires_at))
                if created is not None:
                    return PreparedOrder(created, product, retried=False)
                existing = await store.order_for_key(user_id, idempotency_key)
            if existing is None:
                raise OrderNotFoundError
            owned = await store.product_by_id(existing.product_id)
        if owned is None or owned.code != product_code:
            raise IdempotencyKeyReusedError("This Idempotency-Key was already used for a different product.")
        return PreparedOrder(existing, owned, retried=True)

    async def _open_remote_order(self, prepared: PreparedOrder) -> OrderRecord:
        rejection: PaymentProviderRejectedError | None = None
        async with self._transaction() as session:
            uncontended = await self._store_factory(session).lock_creation(prepared.order.id)
            order = await self._current(prepared.order)
            if order.status is not OrderStatus.CREATED:
                return self._require_pending(order)
            try:
                remote = await self._remote_order(order, look_first=prepared.retried or not uncontended)
            except PaymentProviderRejectedError as error:
                rejection = error
            else:
                if remote.amount != order.amount_paise or remote.currency != order.currency:
                    raise PaymentProviderError("The payment provider order does not match the stored order.")
                return await self._attach(order, remote.id)
        raise rejection

    async def _current(self, order: OrderRecord) -> OrderRecord:
        async with self._transaction() as session:
            current = await self._store_factory(session).order_for_key(order.user_id, order.idempotency_key)
        if current is None:
            raise OrderNotFoundError
        return current

    @staticmethod
    def _require_pending(order: OrderRecord) -> OrderRecord:
        if order.status is not OrderStatus.PENDING:
            raise OrderNotPayableError("This order can no longer be paid. Start a new purchase.")
        return order

    async def _remote_order(self, order: OrderRecord, *, look_first: bool) -> RazorpayOrder:
        if look_first:
            found = await self._find(order.receipt)
            if found is not None:
                return found
        try:
            return await self._razorpay.create_order(
                amount=order.amount_paise,
                currency=order.currency,
                receipt=order.receipt,
                notes={"userId": str(order.user_id), "orderId": str(order.id)},
            )
        except RazorpayBadRequestError as error:
            await self._fail(order, error)
            raise PaymentProviderRejectedError("The payment provider rejected the order.") from error
        except RazorpayError as error:
            if not is_ambiguous(error):
                raise provider_error(error) from error
            found = await self._find(order.receipt)
            if found is None:
                raise provider_error(error) from error
            return found

    async def _find(self, receipt: str) -> RazorpayOrder | None:
        try:
            return await self._razorpay.find_order_by_receipt(receipt)
        except RazorpayError as error:
            raise provider_error(error) from error

    async def _fail(self, order: OrderRecord, error: RazorpayApiError) -> None:
        async with self._transaction() as session:
            await transition_order(
                self._store_factory(session),
                order.id,
                OrderStatus.CREATED,
                OrderStatus.FAILED,
                {"failure_reason": rejection_reason(error)},
            )

    async def _attach(self, order: OrderRecord, razorpay_order_id: str) -> OrderRecord:
        async with self._transaction() as session:
            store = self._store_factory(session)
            moved = await transition_order(
                store, order.id, OrderStatus.CREATED, OrderStatus.PENDING, {"razorpay_order_id": razorpay_order_id}
            )
            current = await store.order_for_key(order.user_id, order.idempotency_key)
        if current is None or (not moved and current.status is not OrderStatus.PENDING):
            raise OrderNotPayableError("This order can no longer be paid. Start a new purchase.")
        return current
