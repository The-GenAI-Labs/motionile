from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.alerts import raise_alert
from motionile.core.clock import Clock
from motionile.core.ids import new_id
from motionile.modules.audit import ActorType, AuditEvent
from motionile.modules.audit import record as record_audit
from motionile.modules.billing.exceptions import UnexpectedOrderStateError
from motionile.modules.billing.ports import Alert, AuditRecorder, StoreFactory
from motionile.modules.billing.razorpay.models import RazorpayPayment
from motionile.modules.billing.records import NewPayment, OrderRecord, PaymentRecord
from motionile.modules.billing.repository import BillingStore, SqlBillingRepository
from motionile.modules.billing.services.decisions import (
    FLAG_AMOUNT_MISMATCH,
    FLAG_CURRENCY_MISMATCH,
    FLAG_DUPLICATE_PAYMENT,
    SettlementDecision,
    SettlementOutcome,
    SettlementResult,
    SettlementSource,
    attempt_status,
    decide_settlement,
)
from motionile.modules.billing.services.receipts import PaymentReceipt, ReceiptSender
from motionile.modules.billing.states import (
    PAYMENT_MACHINE,
    OrderStatus,
    PaymentRecordStatus,
)
from motionile.modules.billing.transitions import transition_order, transition_payment
from motionile.modules.credits import CreditRef, CreditsService, GrantCommand

PAYMENT_KEY_PREFIX = "payment"
FALLBACK_PRODUCT_NAME = "Credit pack"
ERROR_DESCRIPTION_LIMIT = 500
ON_TIME_STATUSES = frozenset({OrderStatus.CREATED, OrderStatus.PENDING})
CAPTURED_FAMILY = frozenset(
    {PaymentRecordStatus.CAPTURED, PaymentRecordStatus.PARTIALLY_REFUNDED, PaymentRecordStatus.REFUNDED}
)
FLAG_BY_DECISION = {
    SettlementDecision.AMOUNT_MISMATCH: FLAG_AMOUNT_MISMATCH,
    SettlementDecision.CURRENCY_MISMATCH: FLAG_CURRENCY_MISMATCH,
    SettlementDecision.DUPLICATE: FLAG_DUPLICATE_PAYMENT,
}
ALERT_BY_DECISION = {
    SettlementDecision.AMOUNT_MISMATCH: "billing.payment_mismatch",
    SettlementDecision.CURRENCY_MISMATCH: "billing.payment_mismatch",
    SettlementDecision.DUPLICATE: "billing.duplicate_payment",
}
OUTCOME_BY_DECISION = {
    SettlementDecision.AMOUNT_MISMATCH: SettlementOutcome.MISMATCH,
    SettlementDecision.CURRENCY_MISMATCH: SettlementOutcome.MISMATCH,
    SettlementDecision.DUPLICATE: SettlementOutcome.DUPLICATE,
}


@dataclass(frozen=True)
class SettlementCase:
    session: AsyncSession
    store: BillingStore
    order: OrderRecord
    payment: RazorpayPayment
    recorded: PaymentRecord
    source: SettlementSource


def payment_key(payment_id: UUID) -> str:
    return f"{PAYMENT_KEY_PREFIX}:{payment_id}"


@dataclass(frozen=True)
class SettlementPorts:
    store_factory: StoreFactory = SqlBillingRepository
    audit: AuditRecorder = record_audit
    alert: Alert = raise_alert


class SettlementService:
    def __init__(
        self,
        clock: Clock,
        credit_service: CreditsService,
        receipts: ReceiptSender,
        ports: SettlementPorts | None = None,
    ) -> None:
        resolved = ports or SettlementPorts()
        self._clock = clock
        self._credits = credit_service
        self._receipts = receipts
        self._store_factory = resolved.store_factory
        self._audit = resolved.audit
        self._alert = resolved.alert

    async def settle(
        self, session: AsyncSession, payment: RazorpayPayment, source: SettlementSource
    ) -> SettlementResult:
        if not payment.is_captured:
            return await self.record_attempt(session, payment)
        store = self._store_factory(session)
        order = await self._locked_order(store, payment)
        if order is None:
            return SettlementResult(SettlementOutcome.UNKNOWN_ORDER)
        existing = await store.payment_by_razorpay_id(payment.id)
        if existing is not None and existing.status is not PaymentRecordStatus.AUTHORIZED:
            if existing.status not in CAPTURED_FAMILY:
                PAYMENT_MACHINE.require(existing.status, PaymentRecordStatus.CAPTURED)
            return SettlementResult(SettlementOutcome.ALREADY_SETTLED, order.id, existing.id, existing.credits_granted)
        recorded = await self._record_captured(store, order, payment, existing)
        case = SettlementCase(session, store, order, payment, recorded, source)
        decision = decide_settlement(order, payment.amount, payment.currency)
        if decision is SettlementDecision.GRANT:
            return await self._grant(case)
        return await self._hold_for_review(case, decision)

    async def record_attempt(self, session: AsyncSession, payment: RazorpayPayment) -> SettlementResult:
        status = attempt_status(payment)
        if status is None:
            return SettlementResult(SettlementOutcome.NOT_RECORDABLE)
        store = self._store_factory(session)
        order = await self._locked_order(store, payment)
        if order is None:
            return SettlementResult(SettlementOutcome.UNKNOWN_ORDER)
        existing = await store.payment_by_razorpay_id(payment.id)
        if existing is None:
            created = await store.insert_payment(
                NewPayment(
                    id=new_id(),
                    order_id=order.id,
                    user_id=order.user_id,
                    razorpay_payment_id=payment.id,
                    amount_paise=payment.amount,
                    currency=payment.currency,
                    status=status,
                    method=payment.method,
                    error_code=payment.error_code,
                    error_description=truncated(payment.error_description),
                )
            )
            return SettlementResult(SettlementOutcome.ATTEMPT_RECORDED, order.id, created.id)
        if existing.status is not status and PAYMENT_MACHINE.allows(existing.status, status):
            await transition_payment(
                store,
                existing.id,
                existing.status,
                status,
                {"error_code": payment.error_code, "error_description": truncated(payment.error_description)},
            )
        return SettlementResult(SettlementOutcome.ATTEMPT_RECORDED, order.id, existing.id)

    async def _locked_order(self, store: BillingStore, payment: RazorpayPayment) -> OrderRecord | None:
        if payment.order_id is None:
            return None
        return await store.lock_order_by_razorpay_id(payment.order_id)

    async def _record_captured(
        self,
        store: BillingStore,
        order: OrderRecord,
        payment: RazorpayPayment,
        existing: PaymentRecord | None,
    ) -> PaymentRecord:
        now = self._clock.now()
        if existing is None:
            return await store.insert_payment(
                NewPayment(
                    id=new_id(),
                    order_id=order.id,
                    user_id=order.user_id,
                    razorpay_payment_id=payment.id,
                    amount_paise=payment.amount,
                    currency=payment.currency,
                    status=PaymentRecordStatus.CAPTURED,
                    method=payment.method,
                    fee_paise=payment.fee,
                    tax_paise=payment.tax,
                    captured_at=now,
                )
            )
        await transition_payment(
            store,
            existing.id,
            existing.status,
            PaymentRecordStatus.CAPTURED,
            {
                "amount_paise": payment.amount,
                "currency": payment.currency,
                "method": payment.method,
                "fee_paise": payment.fee,
                "tax_paise": payment.tax,
                "captured_at": now,
                "error_code": None,
                "error_description": None,
            },
        )
        refreshed = await store.payment_by_razorpay_id(payment.id)
        if refreshed is None:
            raise UnexpectedOrderStateError(str(order.id), "linked to its payment")
        return refreshed

    async def _grant(self, case: SettlementCase) -> SettlementResult:
        order = case.order
        now = self._clock.now()
        previous = order.status
        if not await transition_order(case.store, order.id, previous, OrderStatus.PAID, {"paid_at": now}):
            raise UnexpectedOrderStateError(str(order.id), previous.value)
        grant = await self._credits.grant(
            case.session,
            GrantCommand(
                user_id=order.user_id,
                amount=order.credits_granted,
                source="purchase",
                key=payment_key(case.recorded.id),
                expires_at=None,
                ref=CreditRef("payment", case.recorded.id),
            ),
        )
        await case.store.set_payment_credits(case.recorded.id, grant.amount)
        await self._audit_event(case, "billing.order.paid", {"credits": grant.amount, "ledgerId": str(grant.ledger_id)})
        if previous not in ON_TIME_STATUSES:
            await self._audit_event(case, "billing.order.settled_late", {"previousStatus": previous.value})
        await self._send_receipt(case, now)
        return SettlementResult(SettlementOutcome.SETTLED, order.id, case.recorded.id, grant.amount)

    async def _hold_for_review(self, case: SettlementCase, decision: SettlementDecision) -> SettlementResult:
        reason = FLAG_BY_DECISION[decision]
        await case.store.flag_order(case.order.id, reason, self._clock.now())
        self._alert(
            ALERT_BY_DECISION[decision],
            reason=reason,
            order_id=str(case.order.id),
            payment_id=str(case.recorded.id),
            razorpay_payment_id=case.payment.id,
            expected_amount_paise=case.order.amount_paise,
            received_amount_paise=case.payment.amount,
            expected_currency=case.order.currency,
            received_currency=case.payment.currency,
        )
        await self._audit_event(
            case,
            "billing.payment.flagged",
            {
                "reason": reason,
                "expectedAmountPaise": case.order.amount_paise,
                "receivedAmountPaise": case.payment.amount,
            },
        )
        return SettlementResult(OUTCOME_BY_DECISION[decision], case.order.id, case.recorded.id)

    async def _audit_event(self, case: SettlementCase, action: str, metadata: dict[str, object]) -> None:
        await self._audit(
            case.session,
            AuditEvent(
                action=action,
                actor_type=ActorType.SYSTEM,
                target_type="order",
                target_id=str(case.order.id),
                metadata={
                    "userId": str(case.order.user_id),
                    "paymentId": str(case.recorded.id),
                    "razorpayPaymentId": case.payment.id,
                    "source": case.source.value,
                    **metadata,
                },
            ),
        )

    async def _send_receipt(self, case: SettlementCase, paid_at: datetime) -> None:
        product = await case.store.product_by_id(case.order.product_id)
        await self._receipts(
            case.session,
            PaymentReceipt(
                user_id=case.order.user_id,
                product_name=product.name if product is not None else FALLBACK_PRODUCT_NAME,
                amount_paise=case.order.amount_paise,
                currency=case.order.currency,
                credits=case.order.credits_granted,
                paid_at=paid_at,
                order_reference=str(case.order.id),
            ),
        )


def truncated(description: str | None) -> str | None:
    return description[:ERROR_DESCRIPTION_LIMIT] if description is not None else None
