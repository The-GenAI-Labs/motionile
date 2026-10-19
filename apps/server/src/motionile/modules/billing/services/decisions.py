from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from motionile.modules.billing.razorpay.models import PaymentStatus, RazorpayPayment
from motionile.modules.billing.records import OrderRecord
from motionile.modules.billing.states import OrderStatus, PaymentRecordStatus

FLAG_AMOUNT_MISMATCH = "amount_mismatch"
FLAG_CURRENCY_MISMATCH = "currency_mismatch"
FLAG_DUPLICATE_PAYMENT = "duplicate_payment"


class SettlementSource(StrEnum):
    VERIFY = "verify"
    WEBHOOK = "webhook"
    RECONCILIATION = "reconciliation"


class SettlementDecision(StrEnum):
    GRANT = "grant"
    AMOUNT_MISMATCH = FLAG_AMOUNT_MISMATCH
    CURRENCY_MISMATCH = FLAG_CURRENCY_MISMATCH
    DUPLICATE = FLAG_DUPLICATE_PAYMENT


class SettlementOutcome(StrEnum):
    SETTLED = "settled"
    ALREADY_SETTLED = "already_settled"
    MISMATCH = "mismatch"
    DUPLICATE = "duplicate"
    UNKNOWN_ORDER = "unknown_order"
    ATTEMPT_RECORDED = "attempt_recorded"
    NOT_RECORDABLE = "not_recordable"


@dataclass(frozen=True)
class SettlementResult:
    outcome: SettlementOutcome
    order_id: UUID | None = None
    payment_id: UUID | None = None
    credits_granted: int = 0

    @property
    def order_paid(self) -> bool:
        return self.outcome in {SettlementOutcome.SETTLED, SettlementOutcome.ALREADY_SETTLED}

    @property
    def needs_attention(self) -> bool:
        return self.outcome in {SettlementOutcome.MISMATCH, SettlementOutcome.DUPLICATE}


def decide_settlement(order: OrderRecord, amount_paise: int, currency: str) -> SettlementDecision:
    if currency != order.currency:
        return SettlementDecision.CURRENCY_MISMATCH
    if amount_paise != order.amount_paise:
        return SettlementDecision.AMOUNT_MISMATCH
    if order.status is OrderStatus.PAID:
        return SettlementDecision.DUPLICATE
    return SettlementDecision.GRANT


def attempt_status(payment: RazorpayPayment) -> PaymentRecordStatus | None:
    if payment.status == PaymentStatus.AUTHORIZED:
        return PaymentRecordStatus.AUTHORIZED
    if payment.status == PaymentStatus.FAILED:
        return PaymentRecordStatus.FAILED
    return None
