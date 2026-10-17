from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, cast

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictInt


class PaymentStatus(StrEnum):
    CREATED = "created"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    FAILED = "failed"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


class SubscriptionStatus(StrEnum):
    CREATED = "created"
    AUTHENTICATED = "authenticated"
    ACTIVE = "active"
    PENDING = "pending"
    HALTED = "halted"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    PAUSED = "paused"
    EXPIRED = "expired"


class OrderStatus(StrEnum):
    CREATED = "created"
    ATTEMPTED = "attempted"
    PAID = "paid"


class RefundStatus(StrEnum):
    PENDING = "pending"
    PROCESSED = "processed"
    FAILED = "failed"


def normalize_notes(value: object) -> object:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        entries = cast("Mapping[object, object]", value)
        return {str(key): str(item) for key, item in entries.items() if item is not None}
    if isinstance(value, list | tuple):
        return {}
    return value


def normalize_count(value: object) -> object:
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    return value


def from_epoch(value: int | None) -> datetime | None:
    return datetime.fromtimestamp(value, UTC) if value is not None else None


Paise = Annotated[StrictInt, Field(ge=0)]
EpochSeconds = StrictInt
Notes = Annotated[dict[str, str], BeforeValidator(normalize_notes)]
Count = Annotated[StrictInt, BeforeValidator(normalize_count)]


class RazorpayModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class RazorpayOrder(RazorpayModel):
    id: str
    amount: Paise
    amount_paid: Paise = 0
    amount_due: Paise = 0
    currency: str
    receipt: str | None = None
    status: str
    attempts: StrictInt = 0
    notes: Notes = Field(default_factory=dict[str, str])
    created_at: EpochSeconds

    @property
    def created_at_utc(self) -> datetime:
        return datetime.fromtimestamp(self.created_at, UTC)


class RazorpayPayment(RazorpayModel):
    id: str
    amount: Paise
    currency: str
    status: str
    order_id: str | None = None
    invoice_id: str | None = None
    method: str | None = None
    captured: bool = False
    amount_refunded: Paise = 0
    refund_status: str | None = None
    fee: Paise | None = None
    tax: Paise | None = None
    email: str | None = None
    contact: str | None = None
    error_code: str | None = None
    error_description: str | None = None
    error_reason: str | None = None
    notes: Notes = Field(default_factory=dict[str, str])
    created_at: EpochSeconds

    @property
    def created_at_utc(self) -> datetime:
        return datetime.fromtimestamp(self.created_at, UTC)

    @property
    def is_captured(self) -> bool:
        return self.captured and self.status in {
            PaymentStatus.CAPTURED,
            PaymentStatus.REFUNDED,
            PaymentStatus.PARTIALLY_REFUNDED,
        }


class RazorpayCustomer(RazorpayModel):
    id: str
    name: str | None = None
    email: str | None = None
    contact: str | None = None
    notes: Notes = Field(default_factory=dict[str, str])
    created_at: EpochSeconds


class RazorpayPlanItem(RazorpayModel):
    id: str | None = None
    name: str
    description: str | None = None
    amount: Paise
    currency: str


class RazorpayPlan(RazorpayModel):
    id: str
    period: str
    interval: StrictInt
    item: RazorpayPlanItem
    notes: Notes = Field(default_factory=dict[str, str])
    created_at: EpochSeconds

    @property
    def amount(self) -> int:
        return self.item.amount

    @property
    def currency(self) -> str:
        return self.item.currency


class RazorpaySubscription(RazorpayModel):
    id: str
    plan_id: str
    customer_id: str | None = None
    status: str
    current_start: EpochSeconds | None = None
    current_end: EpochSeconds | None = None
    ended_at: EpochSeconds | None = None
    charge_at: EpochSeconds | None = None
    start_at: EpochSeconds | None = None
    end_at: EpochSeconds | None = None
    quantity: StrictInt = 1
    total_count: Count
    paid_count: Count = 0
    remaining_count: Count | None = None
    auth_attempts: StrictInt = 0
    customer_notify: bool = True
    has_scheduled_changes: bool = False
    change_scheduled_at: EpochSeconds | None = None
    short_url: str | None = None
    notes: Notes = Field(default_factory=dict[str, str])
    created_at: EpochSeconds

    @property
    def created_at_utc(self) -> datetime:
        return datetime.fromtimestamp(self.created_at, UTC)

    @property
    def current_start_utc(self) -> datetime | None:
        return from_epoch(self.current_start)

    @property
    def current_end_utc(self) -> datetime | None:
        return from_epoch(self.current_end)

    @property
    def charge_at_utc(self) -> datetime | None:
        return from_epoch(self.charge_at)

    @property
    def ended_at_utc(self) -> datetime | None:
        return from_epoch(self.ended_at)

    @property
    def start_at_utc(self) -> datetime | None:
        return from_epoch(self.start_at)

    @property
    def change_scheduled_at_utc(self) -> datetime | None:
        return from_epoch(self.change_scheduled_at)


class RazorpayRefund(RazorpayModel):
    id: str
    payment_id: str
    amount: Paise
    currency: str = "INR"
    status: str
    receipt: str | None = None
    speed_processed: str | None = None
    speed_requested: str | None = None
    notes: Notes = Field(default_factory=dict[str, str])
    created_at: EpochSeconds

    @property
    def created_at_utc(self) -> datetime:
        return datetime.fromtimestamp(self.created_at, UTC)
