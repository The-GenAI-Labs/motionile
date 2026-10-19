from motionile.modules.billing.exceptions import RefundExceedsRefundableError
from motionile.modules.billing.states import PaymentRecordStatus

EXTERNAL_KEY_PREFIX = "external:"
EXTERNAL_REASON = "external_refund"
REFUNDABLE_PAYMENT_STATUSES = frozenset({PaymentRecordStatus.CAPTURED, PaymentRecordStatus.PARTIALLY_REFUNDED})


def settled_payment_status(*, amount_paise: int, refunded_paise: int) -> PaymentRecordStatus:
    if refunded_paise <= 0:
        return PaymentRecordStatus.CAPTURED
    return refund_payment_status(amount_paise=amount_paise, refunded_paise=refunded_paise)


def refundable_paise(*, amount_paise: int, refunded_paise: int, pending_paise: int) -> int:
    return amount_paise - refunded_paise - pending_paise


def resolve_refund_amount(requested_paise: int | None, refundable: int) -> int:
    amount = refundable if requested_paise is None else requested_paise
    if amount <= 0 or amount > refundable:
        raise RefundExceedsRefundableError(refundable)
    return amount


def refund_payment_status(*, amount_paise: int, refunded_paise: int) -> PaymentRecordStatus:
    if refunded_paise >= amount_paise:
        return PaymentRecordStatus.REFUNDED
    return PaymentRecordStatus.PARTIALLY_REFUNDED


def proportional_credits(*, credits_granted: int, payment_amount_paise: int, refund_amount_paise: int) -> int:
    if credits_granted <= 0 or payment_amount_paise <= 0 or refund_amount_paise <= 0:
        return 0
    return -(-credits_granted * refund_amount_paise // payment_amount_paise)


def credits_after_refund(*, credits_granted: int, payment_amount_paise: int, refunded_paise: int) -> int:
    refunded = max(0, min(refunded_paise, payment_amount_paise))
    return credits_granted - proportional_credits(
        credits_granted=credits_granted, payment_amount_paise=payment_amount_paise, refund_amount_paise=refunded
    )


def clawback_amount(
    *,
    credits_granted: int,
    payment_amount_paise: int,
    refund_amount_paise: int,
    already_clawed_back: int,
    lot_remaining: int,
) -> int:
    proportional = proportional_credits(
        credits_granted=credits_granted,
        payment_amount_paise=payment_amount_paise,
        refund_amount_paise=refund_amount_paise,
    )
    return max(0, min(proportional, credits_granted - already_clawed_back, lot_remaining))
