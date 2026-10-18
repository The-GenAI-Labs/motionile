from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from motionile.core.clock import Clock
from motionile.core.config import BillingSettings
from motionile.core.idempotency import IdempotencyKeyReusedError
from motionile.core.ids import new_id
from motionile.modules.audit import ActorType, AuditEvent
from motionile.modules.billing.exceptions import (
    OrderNotFoundError,
    OrderNotPayableError,
    PaymentProviderRejectedError,
    ProductNotFoundError,
    ProductNotPurchasableError,
    SubscriptionExistsError,
    SubscriptionNotFoundError,
)
from motionile.modules.billing.ports import AuditRecorder, StoreFactory, Transaction
from motionile.modules.billing.razorpay.api import MAX_LIST_COUNT, RazorpayApi
from motionile.modules.billing.razorpay.exceptions import RazorpayBadRequestError, RazorpayError
from motionile.modules.billing.razorpay.models import RazorpaySubscription
from motionile.modules.billing.records import (
    NewOrder,
    NewSubscription,
    OrderRecord,
    ProductRecord,
    SubscriptionRecord,
)
from motionile.modules.billing.repository import BillingStore
from motionile.modules.billing.schemas import CheckoutPrefillResponse, SubscriptionCheckoutResponse
from motionile.modules.billing.services.checkout import CHECKOUT_NAME
from motionile.modules.billing.services.customers import CustomerProfile, CustomerService
from motionile.modules.billing.services.orders import KeyIdSource, rejection_reason
from motionile.modules.billing.services.provider import is_ambiguous, provider_error
from motionile.modules.billing.states import OrderStatus, SubscriptionStatus
from motionile.modules.billing.transitions import transition_order, transition_subscription

SUBSCRIPTION_KIND = "subscription"
LOOKUP_MARGIN = timedelta(minutes=10)
LOOKUP_MAX_PAGES = 10
PAYABLE_ORDER_STATUSES = frozenset({OrderStatus.CREATED, OrderStatus.PENDING})


class KeyRaceError(Exception):
    pass


@dataclass(frozen=True)
class PreparedSubscription:
    subscription: SubscriptionRecord
    order: OrderRecord
    product: ProductRecord
    retried: bool


@dataclass(frozen=True)
class SubscriptionDependencies:
    transaction: Transaction
    razorpay: RazorpayApi
    customers: CustomerService
    clock: Clock
    settings: BillingSettings
    key_id: KeyIdSource
    audit: AuditRecorder


def plan_product_or_raise(product: ProductRecord | None) -> ProductRecord:
    if product is None or not product.is_active:
        raise ProductNotFoundError
    if product.kind != SUBSCRIPTION_KIND or product.razorpay_plan_id is None:
        raise ProductNotPurchasableError("This product is not a subscription plan.")
    return product


class SubscriptionCheckout:
    def __init__(self, deps: SubscriptionDependencies, store_factory: StoreFactory) -> None:
        self._transaction = deps.transaction
        self._razorpay = deps.razorpay
        self._customers = deps.customers
        self._clock = deps.clock
        self._settings = deps.settings
        self._key_id = deps.key_id
        self._audit = deps.audit
        self._store_factory = store_factory

    async def create(self, user_id: UUID, product_code: str, idempotency_key: str) -> SubscriptionCheckoutResponse:
        prepared = await self._prepare(user_id, product_code, idempotency_key)
        subscription, order = prepared.subscription, prepared.order
        if order.status not in PAYABLE_ORDER_STATUSES or subscription.status is not SubscriptionStatus.CREATED:
            raise OrderNotPayableError("This subscription can no longer be paid. Start a new one.")
        customer = await self._customers.ensure(user_id)
        remote_id = subscription.razorpay_subscription_id
        if remote_id is None:
            remote_id = (await self._open_remote(prepared)).id
        if subscription.razorpay_subscription_id is None or order.status is OrderStatus.CREATED:
            subscription, order = await self._attach(prepared, remote_id)
        return self._checkout(subscription, order, prepared.product, customer)

    async def _prepare(self, user_id: UUID, product_code: str, idempotency_key: str) -> PreparedSubscription:
        try:
            return await self._prepare_once(user_id, product_code, idempotency_key)
        except KeyRaceError:
            return await self._prepare_once(user_id, product_code, idempotency_key)

    async def _prepare_once(self, user_id: UUID, product_code: str, idempotency_key: str) -> PreparedSubscription:
        async with self._transaction() as session:
            store = self._store_factory(session)
            existing = await store.order_for_key(user_id, idempotency_key)
            if existing is not None:
                return await self._resume(store, existing, product_code)
            product = plan_product_or_raise(await store.product_by_code(product_code))
            if await store.live_subscription(user_id) is not None:
                raise SubscriptionExistsError("You already have a subscription.")
            subscription = await store.insert_subscription(
                NewSubscription(new_id(), user_id, product.id, self._settings.subscription_total_count)
            )
            expires_at = self._clock.now() + timedelta(seconds=self._settings.order_expiry_seconds)
            order = await store.insert_order(
                NewOrder(new_id(), user_id, product, idempotency_key, expires_at, subscription_id=subscription.id)
            )
            if order is None:
                raise KeyRaceError
            return PreparedSubscription(subscription, order, product, retried=False)

    async def _resume(self, store: BillingStore, order: OrderRecord, product_code: str) -> PreparedSubscription:
        if order.subscription_id is None:
            raise IdempotencyKeyReusedError("This Idempotency-Key was already used for a different purchase.")
        product = await store.product_by_id(order.product_id)
        if product is None or product.code != product_code:
            raise IdempotencyKeyReusedError("This Idempotency-Key was already used for a different product.")
        subscription = await store.subscription_for_user(order.subscription_id, order.user_id)
        if subscription is None:
            raise OrderNotFoundError
        return PreparedSubscription(subscription, order, product, retried=True)

    async def _open_remote(self, prepared: PreparedSubscription) -> RazorpaySubscription:
        if prepared.retried:
            found = await self._find(prepared)
            if found is not None:
                return found
        try:
            return await self._razorpay.create_subscription(
                plan_id=self._plan_id(prepared),
                total_count=prepared.subscription.total_count,
                notes={
                    "userId": str(prepared.subscription.user_id),
                    "orderId": str(prepared.order.id),
                    "subscriptionId": str(prepared.subscription.id),
                },
                customer_notify=False,
            )
        except RazorpayBadRequestError as error:
            await self._fail(prepared, rejection_reason(error))
            raise PaymentProviderRejectedError("The payment provider rejected the subscription.") from error
        except RazorpayError as error:
            if not is_ambiguous(error):
                raise provider_error(error) from error
            found = await self._find(prepared)
            if found is None:
                raise provider_error(error) from error
            return found

    @staticmethod
    def _plan_id(prepared: PreparedSubscription) -> str:
        plan_id = prepared.product.razorpay_plan_id
        if plan_id is None:
            raise ProductNotPurchasableError("This product is not a subscription plan.")
        return plan_id

    async def _find(self, prepared: PreparedSubscription) -> RazorpaySubscription | None:
        now = self._clock.now()
        window_start = now - timedelta(seconds=self._settings.order_expiry_seconds) - LOOKUP_MARGIN
        try:
            for page in range(LOOKUP_MAX_PAGES):
                candidates = await self._razorpay.list_subscriptions(
                    plan_id=self._plan_id(prepared),
                    from_ts=window_start,
                    to_ts=now + LOOKUP_MARGIN,
                    count=MAX_LIST_COUNT,
                    skip=page * MAX_LIST_COUNT,
                )
                for candidate in candidates:
                    if candidate.notes.get("subscriptionId") == str(prepared.subscription.id):
                        return candidate
                if len(candidates) < MAX_LIST_COUNT:
                    return None
        except RazorpayError as error:
            raise provider_error(error) from error
        return None

    async def _fail(self, prepared: PreparedSubscription, reason: str) -> None:
        async with self._transaction() as session:
            store = self._store_factory(session)
            await store.lock_subscription_for_user(prepared.subscription.id, prepared.subscription.user_id)
            await transition_order(
                store, prepared.order.id, OrderStatus.CREATED, OrderStatus.FAILED, {"failure_reason": reason}
            )
            await transition_subscription(
                store,
                prepared.subscription.id,
                SubscriptionStatus.CREATED,
                SubscriptionStatus.EXPIRED,
                {"ended_at": self._clock.now()},
            )

    async def _attach(
        self, prepared: PreparedSubscription, razorpay_subscription_id: str
    ) -> tuple[SubscriptionRecord, OrderRecord]:
        subscription_id = prepared.subscription.id
        user_id = prepared.subscription.user_id
        async with self._transaction() as session:
            store = self._store_factory(session)
            locked = await store.lock_subscription_for_user(subscription_id, user_id)
            order = await store.lock_order(prepared.order.id)
            if locked is None or order is None:
                raise SubscriptionNotFoundError
            if locked.razorpay_subscription_id is None:
                await store.update_subscription(subscription_id, {"razorpay_subscription_id": razorpay_subscription_id})
            if order.status is OrderStatus.CREATED:
                await transition_order(store, order.id, OrderStatus.CREATED, OrderStatus.PENDING)
            refreshed = await store.subscription_for_user(subscription_id, user_id)
            current_order = await store.lock_order(order.id)
            await self._audit(
                session,
                AuditEvent(
                    action="billing.subscription.created",
                    actor_type=ActorType.USER,
                    actor_user_id=user_id,
                    target_type="subscription",
                    target_id=str(subscription_id),
                    metadata={"productCode": prepared.product.code, "razorpaySubscriptionId": razorpay_subscription_id},
                ),
            )
        if refreshed is None or current_order is None:
            raise SubscriptionNotFoundError
        return refreshed, current_order

    def _checkout(
        self,
        subscription: SubscriptionRecord,
        order: OrderRecord,
        product: ProductRecord,
        customer: CustomerProfile,
    ) -> SubscriptionCheckoutResponse:
        if subscription.razorpay_subscription_id is None:
            message = "checkout data needs a subscription that exists at the payment provider"
            raise ValueError(message)
        return SubscriptionCheckoutResponse(
            order_id=order.id,
            subscription_id=subscription.id,
            key_id=self._key_id(),
            razorpay_subscription_id=subscription.razorpay_subscription_id,
            name=CHECKOUT_NAME,
            description=product.name,
            customer_id=customer.razorpay_customer_id,
            prefill=CheckoutPrefillResponse(name=customer.name, email=customer.email, contact=customer.contact),
        )
