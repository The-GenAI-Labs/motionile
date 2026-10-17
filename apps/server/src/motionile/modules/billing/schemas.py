from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from motionile.core.schemas import CursorPage, ResponseModel, StrictModel

PRODUCT_CODE_PATTERN = r"^[a-z0-9]+(_[a-z0-9]+)*$"
RAZORPAY_ID_PATTERN = r"^[A-Za-z0-9_]+$"
MAX_RAZORPAY_ID_LENGTH = 64
MAX_SIGNATURE_LENGTH = 128
MAX_PRODUCT_CODE_LENGTH = 60

type OrderStatusName = Literal["created", "pending", "paid", "failed", "expired", "cancelled"]
type OrderKindName = Literal["credit_pack", "subscription"]
type IntervalName = Literal["month", "year"]
type VerifiedStatus = Literal["paid", "pending"]
type WebhookReceiptStatus = Literal["received", "duplicate"]
type HistoryTypeName = Literal["order", "payment", "refund"]


def only_strings(value: object) -> object:
    if isinstance(value, list | tuple):
        return [item for item in cast("Sequence[object]", value) if isinstance(item, str)]
    return value


class ProductResponse(ResponseModel):
    code: str
    name: str
    description: str | None
    price_paise: int
    currency: str
    interval: IntervalName | None
    plan_key: str | None
    credits_granted: int
    features: Annotated[list[str], BeforeValidator(only_strings)]
    sort_order: int


class ProductsResponse(ResponseModel):
    credit_packs: list[ProductResponse]
    subscriptions: list[ProductResponse]


class CreateOrderRequest(StrictModel):
    product_code: str = Field(min_length=1, max_length=MAX_PRODUCT_CODE_LENGTH, pattern=PRODUCT_CODE_PATTERN)


class CheckoutPrefillResponse(ResponseModel):
    name: str | None
    email: str | None
    contact: str | None


class CheckoutResponse(ResponseModel):
    order_id: UUID
    key_id: str
    razorpay_order_id: str
    amount_paise: int
    currency: str
    name: str
    description: str
    customer_id: str
    prefill: CheckoutPrefillResponse


class OrderResponse(ResponseModel):
    id: UUID
    status: OrderStatusName
    kind: OrderKindName
    product_code: str
    product_name: str
    amount_paise: int
    currency: str
    credits_granted: int
    paid_at: datetime | None
    expires_at: datetime
    failure_reason: str | None = None


class VerifyPaymentRequest(StrictModel):
    razorpay_order_id: str = Field(min_length=1, max_length=MAX_RAZORPAY_ID_LENGTH, pattern=RAZORPAY_ID_PATTERN)
    razorpay_payment_id: str = Field(min_length=1, max_length=MAX_RAZORPAY_ID_LENGTH, pattern=RAZORPAY_ID_PATTERN)
    razorpay_signature: str = Field(min_length=1, max_length=MAX_SIGNATURE_LENGTH)


class VerifyPaymentResponse(ResponseModel):
    order_id: UUID
    status: VerifiedStatus
    credits_granted: int


class HistoryItemResponse(ResponseModel):
    type: HistoryTypeName
    id: UUID
    status: str
    amount_paise: int
    currency: str
    title: str
    credits_granted: int | None = None
    created_at: datetime
    order_id: UUID | None = None
    payment_id: UUID | None = None


class HistoryPageResponse(CursorPage[HistoryItemResponse]):
    pass


class WebhookReceiptResponse(ResponseModel):
    status: WebhookReceiptStatus


class WebhookEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    event: str = Field(min_length=1, max_length=100)
    created_at: int | None = Field(default=None, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict[str, Any])
