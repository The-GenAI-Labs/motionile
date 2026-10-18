from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from motionile.modules.billing.razorpay.models import RazorpayPayment
from motionile.modules.billing.records import LocalPayment
from motionile.modules.billing.states import PaymentRecordStatus

REPORT_MISMATCH_LIMIT = 1_000
CAPTURED_FAMILY = frozenset(
    {PaymentRecordStatus.CAPTURED, PaymentRecordStatus.PARTIALLY_REFUNDED, PaymentRecordStatus.REFUNDED}
)

type JsonObject = dict[str, Any]


class DiscrepancyKind(StrEnum):
    MISSING = "missing"
    EXTRA = "extra"
    MISMATCHED = "mismatched"


class DifferingField(StrEnum):
    AMOUNT = "amount"
    CURRENCY = "currency"
    STATUS = "status"
    REFUNDED = "refunded"


@dataclass(frozen=True)
class PaymentSide:
    amount_paise: int
    currency: str
    status: str
    refunded_paise: int

    def as_json(self) -> JsonObject:
        return {
            "amountPaise": self.amount_paise,
            "currency": self.currency,
            "status": self.status,
            "refundedPaise": self.refunded_paise,
        }


@dataclass(frozen=True)
class Discrepancy:
    kind: DiscrepancyKind
    razorpay_payment_id: str
    remote: PaymentSide | None
    local: PaymentSide | None
    fields: tuple[DifferingField, ...] = ()

    def as_json(self) -> JsonObject:
        return {
            "kind": self.kind.value,
            "razorpayPaymentId": self.razorpay_payment_id,
            "fields": [item.value for item in self.fields],
            "remote": self.remote.as_json() if self.remote is not None else None,
            "local": self.local.as_json() if self.local is not None else None,
        }


def remote_side(payment: RazorpayPayment) -> PaymentSide:
    return PaymentSide(payment.amount, payment.currency, payment.status, payment.amount_refunded)


def local_side(local: LocalPayment) -> PaymentSide:
    payment = local.payment
    return PaymentSide(
        payment.amount_paise,
        payment.currency,
        payment.status.value,
        payment.refunded_paise + local.pending_refund_paise,
    )


def differing_fields(remote: RazorpayPayment, local: LocalPayment) -> tuple[DifferingField, ...]:
    payment = local.payment
    found: list[DifferingField] = []
    if remote.amount != payment.amount_paise:
        found.append(DifferingField.AMOUNT)
    if remote.currency != payment.currency:
        found.append(DifferingField.CURRENCY)
    if remote.is_captured != (payment.status in CAPTURED_FAMILY):
        found.append(DifferingField.STATUS)
    if remote.amount_refunded != payment.refunded_paise + local.pending_refund_paise:
        found.append(DifferingField.REFUNDED)
    return tuple(found)


def compare_payment(remote: RazorpayPayment, local: LocalPayment | None) -> Discrepancy | None:
    if local is None:
        if not remote.is_captured:
            return None
        return Discrepancy(DiscrepancyKind.MISSING, remote.id, remote_side(remote), None)
    fields = differing_fields(remote, local)
    if not fields:
        return None
    return Discrepancy(DiscrepancyKind.MISMATCHED, remote.id, remote_side(remote), local_side(local), fields)


def extra_payment(local: LocalPayment) -> Discrepancy:
    return Discrepancy(DiscrepancyKind.EXTRA, local.payment.razorpay_payment_id, None, local_side(local))


@dataclass
class DiffTally:
    checked: int = 0
    counts: dict[DiscrepancyKind, int] = field(default_factory=dict[DiscrepancyKind, int])
    listed: list[Discrepancy] = field(default_factory=list[Discrepancy])

    def examined(self) -> None:
        self.checked += 1

    def add(self, discrepancy: Discrepancy) -> None:
        self.counts[discrepancy.kind] = self.counts.get(discrepancy.kind, 0) + 1
        if len(self.listed) < REPORT_MISMATCH_LIMIT:
            self.listed.append(discrepancy)

    def count(self, kind: DiscrepancyKind) -> int:
        return self.counts.get(kind, 0)

    @property
    def mismatches(self) -> int:
        return sum(self.counts.values())

    @property
    def truncated(self) -> bool:
        return self.mismatches > len(self.listed)

    def summary(self) -> JsonObject:
        return {kind.value: self.count(kind) for kind in DiscrepancyKind}
