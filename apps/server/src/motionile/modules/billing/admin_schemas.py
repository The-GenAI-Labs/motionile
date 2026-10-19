from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from motionile.core.schemas import CursorPage, PageQuery, ResponseModel, StrictModel
from motionile.modules.billing.schemas import (
    PRODUCT_CODE_PATTERN,
    IntervalName,
    OrderKindName,
    OrderStatusName,
    RefundStatusName,
    SubscriptionStatusName,
)

MAX_PRICE_PAISE = 10_000_000_000
MAX_CREDITS = 100_000_000
MAX_SORT_ORDER = 100_000
MAX_FEATURES = 20
MAX_NAME_LENGTH = 80
MAX_DESCRIPTION_LENGTH = 500
MAX_FEATURE_LENGTH = 120
MAX_SEARCH_LENGTH = 80
MAX_EVENT_TYPE_LENGTH = 100
MAX_PLAN_KEY_LENGTH = 60
NON_NULL_FIELDS = frozenset({"name", "features", "sort_order", "kind", "price_paise", "currency", "credits_granted"})

type ProductKindName = Literal["credit_pack", "subscription"]
type PaymentStatusName = Literal["authorized", "captured", "failed", "refunded", "partially_refunded"]
type WebhookStatusName = Literal["received", "processing", "processed", "failed", "ignored"]
type RunTypeName = Literal["pending_orders", "subscriptions", "settlement"]
type RunStatusName = Literal["running", "completed", "failed"]
type FlagReasonName = Literal["amount_mismatch", "currency_mismatch", "duplicate_payment"]

ProductName = Annotated[str, Field(min_length=1, max_length=MAX_NAME_LENGTH)]
ProductDescription = Annotated[str, Field(min_length=1, max_length=MAX_DESCRIPTION_LENGTH)]
FeatureText = Annotated[str, Field(min_length=1, max_length=MAX_FEATURE_LENGTH)]
FeatureList = Annotated[list[FeatureText], Field(max_length=MAX_FEATURES)]
PriceInPaise = Annotated[int, Field(ge=1, le=MAX_PRICE_PAISE)]
CreditAmount = Annotated[int, Field(ge=1, le=MAX_CREDITS)]
SortOrder = Annotated[int, Field(ge=0, le=MAX_SORT_ORDER)]
CurrencyCode = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
PlanKey = Annotated[str, Field(min_length=1, max_length=MAX_PLAN_KEY_LENGTH, pattern=PRODUCT_CODE_PATTERN)]


class ProductListQuery(PageQuery):
    kind: ProductKindName | None = None
    is_active: bool | None = None
    is_sample: bool | None = None
    search: str | None = Field(default=None, min_length=1, max_length=MAX_SEARCH_LENGTH)


class CreateProductRequest(StrictModel):
    code: str = Field(min_length=1, max_length=60, pattern=PRODUCT_CODE_PATTERN)
    kind: ProductKindName
    name: ProductName
    description: ProductDescription | None = None
    price_paise: PriceInPaise
    currency: CurrencyCode = "INR"
    credits_granted: CreditAmount
    plan_key: PlanKey | None = None
    interval: IntervalName | None = None
    features: FeatureList = Field(default_factory=list[str])
    sort_order: SortOrder = 0
    is_active: bool = Field(default=False, description="Ignored for subscriptions, which start inactive")


class UpdateProductRequest(StrictModel):
    version: int = Field(ge=1)
    name: ProductName | None = None
    description: ProductDescription | None = None
    features: FeatureList | None = None
    sort_order: SortOrder | None = None
    kind: ProductKindName | None = None
    price_paise: PriceInPaise | None = None
    currency: CurrencyCode | None = None
    interval: IntervalName | None = None
    credits_granted: CreditAmount | None = None
    plan_key: PlanKey | None = None

    @model_validator(mode="after")
    def require_changes(self) -> Self:
        provided = self.model_fields_set - {"version"}
        if not provided:
            message = "Send at least one field to change"
            raise ValueError(message)
        nulled = sorted(name for name in provided & NON_NULL_FIELDS if getattr(self, name) is None)
        if nulled:
            message = f"{', '.join(nulled)} cannot be null"
            raise ValueError(message)
        return self

    def changes(self) -> dict[str, object]:
        provided = self.model_fields_set - {"version"}
        return {
            name: tuple(self.features or ()) if name == "features" else getattr(self, name) for name in sorted(provided)
        }


class DuplicateProductRequest(StrictModel):
    name: ProductName | None = None
    description: ProductDescription | None = None
    price_paise: PriceInPaise | None = None
    credits_granted: CreditAmount | None = None
    interval: IntervalName | None = None
    features: FeatureList | None = None


class ProductLinkResponse(ResponseModel):
    id: UUID
    code: str
    name: str
    version: int


class AdminProductResponse(ResponseModel):
    id: UUID
    code: str
    kind: ProductKindName
    plan_key: str | None
    name: str
    description: str | None
    price_paise: int
    currency: str
    interval: IntervalName | None
    credits_granted: int
    razorpay_plan_id: str | None
    is_active: bool
    is_sample: bool
    sort_order: int
    features: list[str]
    version: int
    is_used: bool
    supersedes_product_id: UUID | None
    created_at: datetime
    updated_at: datetime


class AdminProductDetailResponse(AdminProductResponse):
    supersedes: ProductLinkResponse | None
    superseded_by: list[ProductLinkResponse]


class AdminProductPageResponse(CursorPage[AdminProductResponse]):
    pass


class PaymentListQuery(PageQuery):
    status: PaymentStatusName | None = None
    user_id: UUID | None = None
    order_id: UUID | None = None
    created_from: AwareDatetime | None = None
    created_to: AwareDatetime | None = None
    flagged: bool | None = None


class ClawbackPreviewQuery(StrictModel):
    amount_paise: int | None = Field(default=None, ge=1, le=MAX_PRICE_PAISE)


class OrderListQuery(PageQuery):
    status: OrderStatusName | None = None
    flagged: bool | None = None
    user_id: UUID | None = None


class RefundListQuery(PageQuery):
    status: RefundStatusName | None = None
    payment_id: UUID | None = None


class SubscriptionListQuery(PageQuery):
    status: SubscriptionStatusName | None = None
    product_id: UUID | None = None
    plan_key: str | None = Field(default=None, min_length=1, max_length=MAX_PLAN_KEY_LENGTH)
    user_id: UUID | None = None


class WebhookListQuery(PageQuery):
    status: WebhookStatusName | None = None
    event_type: str | None = Field(default=None, min_length=1, max_length=MAX_EVENT_TYPE_LENGTH)
    received_from: AwareDatetime | None = None
    received_to: AwareDatetime | None = None


class RunListQuery(PageQuery):
    type: RunTypeName | None = None
    status: RunStatusName | None = None
    has_mismatches: bool | None = None


class AdminSubscriptionCancelRequest(StrictModel):
    immediately: bool


class AdminOrderResponse(ResponseModel):
    id: UUID
    user_id: UUID
    status: OrderStatusName
    kind: OrderKindName
    product_id: UUID
    product_code: str
    product_name: str
    product_version: int
    amount_paise: int
    currency: str
    credits_granted: int
    razorpay_order_id: str | None
    subscription_id: UUID | None
    receipt: str
    failure_reason: str | None
    flagged_at: datetime | None
    flag_reason: FlagReasonName | None
    expires_at: datetime
    paid_at: datetime | None
    created_at: datetime


class AdminPaymentResponse(ResponseModel):
    id: UUID
    razorpay_payment_id: str
    user_id: UUID
    order_id: UUID | None
    subscription_id: UUID | None
    status: PaymentStatusName
    amount_paise: int
    currency: str
    method: str | None
    fee_paise: int | None
    tax_paise: int | None
    credits_granted: int
    refunded_paise: int
    error_code: str | None
    error_description: str | None
    product_code: str | None
    product_name: str | None
    flagged: bool
    captured_at: datetime | None
    created_at: datetime


class AdminOrderDetailResponse(AdminOrderResponse):
    payments: list[AdminPaymentResponse]


class AdminRefundResponse(ResponseModel):
    id: UUID
    payment_id: UUID
    user_id: UUID
    status: RefundStatusName
    amount_paise: int
    currency: str
    payment_amount_paise: int
    reason: str
    credits_clawed_back: int
    razorpay_refund_id: str | None
    initiated_by: UUID | None
    failure_reason: str | None
    processed_at: datetime | None
    created_at: datetime


class AdminLotResponse(ResponseModel):
    id: UUID
    source: Literal["purchase", "subscription", "admin", "promo"]
    amount: int
    remaining: int
    expires_at: datetime | None
    expired_at: datetime | None
    ref_type: str | None
    ref_id: UUID | None
    created_at: datetime


class ClawbackPreviewResponse(ResponseModel):
    amount_paise: int
    credits_to_claw_back: int


class PaymentSubscriptionResponse(ResponseModel):
    id: UUID
    status: SubscriptionStatusName
    product_code: str
    product_name: str
    plan_key: str | None
    interval: IntervalName | None


class AdminPaymentDetailResponse(AdminPaymentResponse):
    order: AdminOrderResponse | None
    subscription: PaymentSubscriptionResponse | None
    refunds: list[AdminRefundResponse]
    lot: AdminLotResponse | None
    refundable_paise: int
    pending_refund_paise: int
    clawback_preview: ClawbackPreviewResponse


class AdminOrderPageResponse(CursorPage[AdminOrderResponse]):
    pass


class AdminPaymentPageResponse(CursorPage[AdminPaymentResponse]):
    pass


class AdminRefundPageResponse(CursorPage[AdminRefundResponse]):
    pass


class AdminSubscriptionProductResponse(ResponseModel):
    id: UUID
    code: str
    name: str
    plan_key: str | None
    interval: IntervalName | None
    price_paise: int
    credits_granted: int
    is_active: bool


class AdminSubscriptionResponse(ResponseModel):
    id: UUID
    user_id: UUID
    status: SubscriptionStatusName
    razorpay_subscription_id: str | None
    product: AdminSubscriptionProductResponse
    pending_product: AdminSubscriptionProductResponse | None
    total_count: int
    paid_count: int
    current_period_start: datetime | None
    current_period_end: datetime | None
    next_charge_at: datetime | None
    cancel_at_period_end: bool
    cancelled_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


class AdminSubscriptionDetailResponse(AdminSubscriptionResponse):
    payments: list[AdminPaymentResponse]
    orders: list[AdminOrderResponse]


class AdminSubscriptionPageResponse(CursorPage[AdminSubscriptionResponse]):
    pass


class AdminWebhookEventResponse(ResponseModel):
    id: UUID
    provider: str
    event_id: str
    event_type: str
    event_created_at: datetime | None
    status: WebhookStatusName
    attempts: int
    last_error: str | None
    ignored_reason: str | None
    received_at: datetime
    processed_at: datetime | None


class AdminWebhookEventDetailResponse(AdminWebhookEventResponse):
    payload: dict[str, object]


class AdminWebhookEventPageResponse(CursorPage[AdminWebhookEventResponse]):
    pass


class WebhookReprocessResponse(ResponseModel):
    id: UUID
    previous_status: WebhookStatusName
    queued: bool


class AdminRunResponse(ResponseModel):
    id: UUID
    type: RunTypeName
    status: RunStatusName
    period_start: datetime | None
    period_end: datetime | None
    checked_count: int
    repaired_count: int
    mismatch_count: int
    summary: dict[str, object]
    has_report: bool
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    created_at: datetime


class AdminRunPageResponse(CursorPage[AdminRunResponse]):
    pass
