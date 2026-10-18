from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import Clock
from motionile.core.ids import new_id
from motionile.modules.audit import ActorType, AuditEvent
from motionile.modules.billing.ports import Alert, AuditRecorder
from motionile.modules.billing.razorpay.models import RazorpayPayment, RazorpaySubscription
from motionile.modules.billing.records import NewPayment, OrderRecord, ProductRecord, SubscriptionRecord
from motionile.modules.billing.repository import BillingStore
from motionile.modules.billing.services.decisions import FLAG_AMOUNT_MISMATCH, FLAG_CURRENCY_MISMATCH
from motionile.modules.billing.services.settlement import payment_key
from motionile.modules.billing.services.subscription_logic import charge_matches_product, grant_expiry
from motionile.modules.billing.states import OrderStatus, PaymentRecordStatus
from motionile.modules.billing.transitions import transition_order
from motionile.modules.credits import CreditRef, CreditsService, GrantCommand

type RolloverSetting = Callable[[AsyncSession], Awaitable[bool]]


@dataclass(frozen=True)
class Charge:
    session: AsyncSession
    store: BillingStore
    subscription: SubscriptionRecord
    remote: RazorpaySubscription
    payment: RazorpayPayment
    product: ProductRecord


@dataclass(frozen=True)
class ChargeResult:
    payment_id: UUID
    credits_granted: int
    first_charge: bool
    recorded_now: bool
    mismatch: bool


@dataclass(frozen=True)
class ChargePorts:
    audit: AuditRecorder
    alert: Alert
    rollover: RolloverSetting


def mismatch_reason(product: ProductRecord, payment: RazorpayPayment) -> str:
    return FLAG_CURRENCY_MISMATCH if payment.currency != product.currency else FLAG_AMOUNT_MISMATCH


class ChargeRecorder:
    def __init__(self, clock: Clock, credit_service: CreditsService, ports: ChargePorts) -> None:
        self._clock = clock
        self._credits = credit_service
        self._audit = ports.audit
        self._alert = ports.alert
        self._rollover = ports.rollover

    async def record(self, charge: Charge) -> ChargeResult:
        existing = await charge.store.payment_by_razorpay_id(charge.payment.id)
        if existing is not None:
            return ChargeResult(existing.id, existing.credits_granted, False, False, False)
        subscription = charge.subscription
        first = await charge.store.subscription_payment_count(subscription.id) == 0
        order = await charge.store.lock_subscription_order(subscription.id)
        linked = order if order is not None and (first or order.status is not OrderStatus.PAID) else None
        recorded = await charge.store.insert_payment(
            NewPayment(
                id=new_id(),
                order_id=linked.id if linked is not None else None,
                subscription_id=subscription.id,
                user_id=subscription.user_id,
                razorpay_payment_id=charge.payment.id,
                amount_paise=charge.payment.amount,
                currency=charge.payment.currency,
                status=PaymentRecordStatus.CAPTURED,
                method=charge.payment.method,
                fee_paise=charge.payment.fee,
                tax_paise=charge.payment.tax,
                captured_at=self._clock.now(),
            )
        )
        if not charge_matches_product(charge.product, charge.payment):
            await self._hold_for_review(charge, recorded.id, linked)
            return ChargeResult(recorded.id, 0, first, True, True)
        granted = await self._grant(charge, recorded.id)
        if linked is not None:
            await self._settle_order(charge, linked, recorded.id)
        return ChargeResult(recorded.id, granted, first, True, False)

    async def _grant(self, charge: Charge, payment_row_id: UUID) -> int:
        period_end = charge.remote.current_end_utc or charge.subscription.current_period_end
        grant = await self._credits.grant(
            charge.session,
            GrantCommand(
                user_id=charge.subscription.user_id,
                amount=charge.product.credits_granted,
                source="subscription",
                key=payment_key(payment_row_id),
                expires_at=grant_expiry(period_end, rollover=await self._rollover(charge.session)),
                ref=CreditRef("payment", payment_row_id),
            ),
        )
        await charge.store.set_payment_credits(payment_row_id, grant.amount)
        await self._record(
            charge,
            "billing.subscription.charged",
            {
                "paymentId": str(payment_row_id),
                "credits": grant.amount,
                "ledgerId": str(grant.ledger_id),
                "productCode": charge.product.code,
            },
        )
        return grant.amount

    async def _settle_order(self, charge: Charge, order: OrderRecord, payment_row_id: UUID) -> None:
        now = self._clock.now()
        moved = await transition_order(charge.store, order.id, order.status, OrderStatus.PAID, {"paid_at": now})
        if moved:
            await self._record(
                charge, "billing.order.paid", {"orderId": str(order.id), "paymentId": str(payment_row_id)}
            )

    async def _hold_for_review(self, charge: Charge, payment_row_id: UUID, order: OrderRecord | None) -> None:
        reason = mismatch_reason(charge.product, charge.payment)
        if order is not None:
            await charge.store.flag_order(order.id, reason, self._clock.now())
        self._alert(
            "billing.payment_mismatch",
            reason=reason,
            subscription_id=str(charge.subscription.id),
            payment_id=str(payment_row_id),
            razorpay_payment_id=charge.payment.id,
            expected_amount_paise=charge.product.price_paise,
            received_amount_paise=charge.payment.amount,
            expected_currency=charge.product.currency,
            received_currency=charge.payment.currency,
        )
        await self._record(
            charge,
            "billing.payment.flagged",
            {
                "reason": reason,
                "paymentId": str(payment_row_id),
                "expectedAmountPaise": charge.product.price_paise,
                "receivedAmountPaise": charge.payment.amount,
            },
        )

    async def _record(self, charge: Charge, action: str, metadata: dict[str, object]) -> None:
        await self._audit(
            charge.session,
            AuditEvent(
                action=action,
                actor_type=ActorType.SYSTEM,
                target_type="subscription",
                target_id=str(charge.subscription.id),
                metadata={
                    "userId": str(charge.subscription.user_id),
                    "razorpayPaymentId": charge.payment.id,
                    "subscriptionStatus": charge.subscription.status.value,
                    **metadata,
                },
            ),
        )
