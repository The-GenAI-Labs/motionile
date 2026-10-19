from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.resources import Resources
from motionile.modules.notifications import enqueue_billing_email
from motionile.modules.users import UsersService

PAISE_PER_RUPEE = Decimal(100)
CENT = Decimal("0.01")
RUPEE_SIGN = "\N{INDIAN RUPEE SIGN}"
DATE_FORMAT = "%d %B %Y"
LAST_GROUP_DIGITS = 3
GROUP_DIGITS = 2
INCLUSIVE_OF_GST = "incl. GST"


@dataclass(frozen=True)
class PaymentReceipt:
    user_id: UUID
    product_name: str
    amount_paise: int
    currency: str
    credits: int
    paid_at: datetime
    order_reference: str


type ReceiptSender = Callable[[AsyncSession, PaymentReceipt], Awaitable[None]]


def group_indian(digits: str) -> str:
    if len(digits) <= LAST_GROUP_DIGITS:
        return digits
    head, tail = digits[:-LAST_GROUP_DIGITS], digits[-LAST_GROUP_DIGITS:]
    groups: list[str] = []
    while head:
        groups.append(head[-GROUP_DIGITS:])
        head = head[:-GROUP_DIGITS]
    return ",".join([*reversed(groups), tail])


def format_amount(amount_paise: int, currency: str) -> str:
    amount = (Decimal(amount_paise) / PAISE_PER_RUPEE).quantize(CENT)
    whole, fraction = f"{amount:.2f}".split(".")
    grouped = f"{group_indian(whole)}.{fraction}"
    return f"{RUPEE_SIGN}{grouped}" if currency == "INR" else f"{currency} {grouped}"


def receipt_context(receipt: PaymentReceipt) -> dict[str, str]:
    return {
        "product": receipt.product_name,
        "amount": f"{format_amount(receipt.amount_paise, receipt.currency)} {INCLUSIVE_OF_GST}",
        "credits": str(receipt.credits),
        "date": receipt.paid_at.strftime(DATE_FORMAT),
        "order": receipt.order_reference,
    }


class BillingMailer:
    def __init__(self, resources: Resources) -> None:
        self._resources = resources

    async def payment_receipt(self, session: AsyncSession, receipt: PaymentReceipt) -> None:
        email = await UsersService(session).primary_verified_email(receipt.user_id)
        if email is None:
            return
        enqueue_billing_email(
            self._resources, session, email=email, template="payment_receipt", context=receipt_context(receipt)
        )
