from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import Clock
from motionile.modules.audit import ActorType, AuditEvent
from motionile.modules.billing.exceptions import (
    InvalidPaymentSignatureError,
    LiveSubscriptionConflictError,
    PaymentProviderError,
    PaymentProviderRejectedError,
    ProductNotFoundError,
    ProductNotPurchasableError,
    SubscriptionExistsError,
    SubscriptionNotChangeableError,
    SubscriptionNotFoundError,
)
from motionile.modules.billing.ports import AuditRecorder, StoreFactory, Transaction
from motionile.modules.billing.razorpay.api import RazorpayApi, ScheduleChangeAt
from motionile.modules.billing.razorpay.exceptions import (
    RazorpayBadRequestError,
    RazorpayError,
    RazorpayNotConfiguredError,
)
from motionile.modules.billing.razorpay.models import RazorpaySubscription
from motionile.modules.billing.razorpay.models import SubscriptionStatus as RemoteStatus
from motionile.modules.billing.razorpay.signatures import verify_subscription_payment_signature
from motionile.modules.billing.records import ProductRecord, SubscriptionRecord, SubscriptionView
from motionile.modules.billing.repository import BillingStore
from motionile.modules.billing.services.notices import NoticeSender, cancellation_notice, ended_notice
from motionile.modules.billing.services.provider import provider_error
from motionile.modules.billing.states import LIVE_SUBSCRIPTION_STATUSES, SubscriptionStatus
from motionile.modules.billing.transitions import transition_subscription

SUBSCRIPTION_KIND = "subscription"
FALLBACK_PLAN_NAME = "Subscription"
NOT_AUTHENTICATED_REMOTE = frozenset({RemoteStatus.CREATED, RemoteStatus.CANCELLED, RemoteStatus.EXPIRED})

type SecretSource = Callable[[], SecretStr]


@dataclass(frozen=True)
class VerifySubscriptionCommand:
    razorpay_payment_id: str
    razorpay_subscription_id: str
    razorpay_signature: str


@dataclass(frozen=True)
class ManagementDependencies:
    transaction: Transaction
    razorpay: RazorpayApi
    clock: Clock
    key_secret: SecretSource
    audit: AuditRecorder
    notices: NoticeSender


@dataclass(frozen=True)
class CancelDecision:
    immediate: bool


class SubscriptionManagement:
    def __init__(self, deps: ManagementDependencies, store_factory: StoreFactory) -> None:
        self._transaction = deps.transaction
        self._razorpay = deps.razorpay
        self._clock = deps.clock
        self._key_secret = deps.key_secret
        self._audit = deps.audit
        self._notices = deps.notices
        self._store_factory = store_factory

    async def current(self, user_id: UUID) -> SubscriptionView | None:
        async with self._transaction() as session:
            store = self._store_factory(session)
            subscription = await store.live_subscription(user_id)
            return await self._view(store, subscription) if subscription is not None else None

    async def verify(self, user_id: UUID, command: VerifySubscriptionCommand) -> SubscriptionView:
        self._require_signature(command)
        async with self._transaction() as session:
            store = self._store_factory(session)
            subscription = await store.lock_subscription_by_razorpay_id_for_user(
                command.razorpay_subscription_id, user_id
            )
            if subscription is None:
                raise SubscriptionNotFoundError
        remote = await self._fetch(command.razorpay_subscription_id)
        async with self._transaction() as session:
            store = self._store_factory(session)
            locked = await store.lock_subscription_for_user(subscription.id, user_id)
            if locked is None:
                raise SubscriptionNotFoundError
            if locked.status is SubscriptionStatus.CREATED and remote.status not in NOT_AUTHENTICATED_REMOTE:
                await self._authenticate(session, store, locked)
            refreshed = await store.subscription_for_user(subscription.id, user_id)
            if refreshed is None:
                raise SubscriptionNotFoundError
            return await self._view(store, refreshed)

    async def cancel(self, user_id: UUID) -> SubscriptionView:
        async with self._transaction() as session:
            store = self._store_factory(session)
            subscription = await store.lock_live_subscription(user_id)
            if subscription is None:
                raise SubscriptionNotFoundError
            if subscription.cancel_at_period_end:
                return await self._view(store, subscription)
        decision = CancelDecision(immediate=subscription.status is not SubscriptionStatus.ACTIVE)
        await self._cancel_remote(subscription, decision)
        async with self._transaction() as session:
            store = self._store_factory(session)
            locked = await store.lock_subscription_for_user(subscription.id, user_id)
            if locked is None:
                raise SubscriptionNotFoundError
            if not locked.cancel_at_period_end and locked.status in LIVE_SUBSCRIPTION_STATUSES:
                await self._record_cancellation(session, store, locked, decision)
            refreshed = await store.subscription_for_user(subscription.id, user_id)
            if refreshed is None:
                raise SubscriptionNotFoundError
            return await self._view(store, refreshed)

    async def change(self, user_id: UUID, product_code: str) -> SubscriptionView:
        async with self._transaction() as session:
            store = self._store_factory(session)
            subscription = await store.lock_live_subscription(user_id)
            if subscription is None:
                raise SubscriptionNotFoundError
            target = await self._changeable_target(store, subscription, product_code)
            if subscription.pending_product_id == target.id:
                return await self._view(store, subscription)
        await self._schedule_remote(subscription, target)
        async with self._transaction() as session:
            store = self._store_factory(session)
            locked = await store.lock_subscription_for_user(subscription.id, user_id)
            if locked is None:
                raise SubscriptionNotFoundError
            self._require_changeable(locked)
            await store.update_subscription(locked.id, {"pending_product_id": target.id})
            await self._audit(
                session,
                AuditEvent(
                    action="billing.subscription.change_scheduled",
                    actor_type=ActorType.USER,
                    actor_user_id=user_id,
                    target_type="subscription",
                    target_id=str(locked.id),
                    metadata={"fromProductId": str(locked.product_id), "toProductCode": target.code},
                ),
            )
            refreshed = await store.subscription_for_user(subscription.id, user_id)
            if refreshed is None:
                raise SubscriptionNotFoundError
            return await self._view(store, refreshed)

    async def _changeable_target(
        self, store: BillingStore, subscription: SubscriptionRecord, product_code: str
    ) -> ProductRecord:
        self._require_changeable(subscription)
        target = await store.product_by_code(product_code)
        if target is None or not target.is_active:
            raise ProductNotFoundError
        if target.kind != SUBSCRIPTION_KIND or target.razorpay_plan_id is None:
            raise ProductNotPurchasableError("This product is not a subscription plan.")
        current = await store.product_by_id(subscription.product_id)
        if current is None or target.id == current.id:
            raise SubscriptionNotChangeableError("You are already on this plan.")
        if target.currency != current.currency:
            raise SubscriptionNotChangeableError("The new plan must be billed in the same currency.")
        return target

    @staticmethod
    def _require_changeable(subscription: SubscriptionRecord) -> None:
        if subscription.status is not SubscriptionStatus.ACTIVE or subscription.cancel_at_period_end:
            raise SubscriptionNotChangeableError("Only an active subscription that is not ending can change plan.")

    async def _schedule_remote(self, subscription: SubscriptionRecord, target: ProductRecord) -> None:
        remote_id = subscription.razorpay_subscription_id
        if remote_id is None or target.razorpay_plan_id is None:
            raise SubscriptionNotChangeableError("This subscription is not ready to change plan.")
        try:
            await self._razorpay.update_subscription(
                remote_id, plan_id=target.razorpay_plan_id, schedule_change_at=ScheduleChangeAt.CYCLE_END
            )
        except RazorpayBadRequestError as error:
            raise PaymentProviderRejectedError("The payment provider rejected the plan change.") from error
        except RazorpayError as error:
            raise provider_error(error) from error

    async def _cancel_remote(self, subscription: SubscriptionRecord, decision: CancelDecision) -> None:
        remote_id = subscription.razorpay_subscription_id
        if remote_id is None:
            raise SubscriptionNotFoundError
        try:
            await self._razorpay.cancel_subscription(remote_id, at_cycle_end=not decision.immediate)
        except RazorpayBadRequestError as error:
            remote = await self._fetch(remote_id)
            if remote.status != RemoteStatus.CANCELLED:
                raise PaymentProviderRejectedError("The payment provider rejected the cancellation.") from error
        except RazorpayError as error:
            raise provider_error(error) from error

    async def _record_cancellation(
        self, session: AsyncSession, store: BillingStore, subscription: SubscriptionRecord, decision: CancelDecision
    ) -> None:
        now = self._clock.now()
        flags = {"cancel_at_period_end": True, "cancelled_at": now}
        product = await store.product_by_id(subscription.product_id)
        plan_name = product.name if product is not None else FALLBACK_PLAN_NAME
        if decision.immediate:
            await transition_subscription(
                store,
                subscription.id,
                subscription.status,
                SubscriptionStatus.CANCELLED,
                {**flags, "ended_at": now},
            )
            await self._notices(session, ended_notice(subscription.user_id, plan_name))
        else:
            await store.update_subscription(subscription.id, flags)
            await self._notices(
                session, cancellation_notice(subscription.user_id, plan_name, subscription.current_period_end)
            )
        await self._audit(
            session,
            AuditEvent(
                action="billing.subscription.cancel_requested",
                actor_type=ActorType.USER,
                actor_user_id=subscription.user_id,
                target_type="subscription",
                target_id=str(subscription.id),
                metadata={"immediate": decision.immediate, "status": subscription.status.value},
            ),
        )

    async def _authenticate(self, session: AsyncSession, store: BillingStore, subscription: SubscriptionRecord) -> None:
        try:
            await transition_subscription(
                store, subscription.id, SubscriptionStatus.CREATED, SubscriptionStatus.AUTHENTICATED
            )
        except LiveSubscriptionConflictError as error:
            raise SubscriptionExistsError("You already have a subscription.") from error
        await self._audit(
            session,
            AuditEvent(
                action="billing.subscription.authenticated",
                actor_type=ActorType.USER,
                actor_user_id=subscription.user_id,
                target_type="subscription",
                target_id=str(subscription.id),
                metadata={"razorpaySubscriptionId": subscription.razorpay_subscription_id},
            ),
        )

    async def _view(self, store: BillingStore, subscription: SubscriptionRecord) -> SubscriptionView:
        product = await store.product_by_id(subscription.product_id)
        if product is None:
            message = f"product {subscription.product_id} is referenced by a subscription but does not exist"
            raise LookupError(message)
        pending = (
            await store.product_by_id(subscription.pending_product_id)
            if subscription.pending_product_id is not None
            else None
        )
        return SubscriptionView(subscription, product, pending)

    def _require_signature(self, command: VerifySubscriptionCommand) -> None:
        try:
            secret = self._key_secret()
        except RazorpayNotConfiguredError as error:
            raise PaymentProviderError("The payment provider is not configured.") from error
        if not verify_subscription_payment_signature(
            command.razorpay_payment_id, command.razorpay_subscription_id, command.razorpay_signature, secret
        ):
            raise InvalidPaymentSignatureError

    async def _fetch(self, razorpay_subscription_id: str) -> RazorpaySubscription:
        try:
            return await self._razorpay.fetch_subscription(razorpay_subscription_id)
        except RazorpayError as error:
            raise provider_error(error) from error
