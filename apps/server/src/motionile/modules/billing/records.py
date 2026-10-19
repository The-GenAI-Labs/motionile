from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from motionile.modules.billing.states import (
    OrderStatus,
    PaymentRecordStatus,
    RefundStatus,
    RunStatus,
    SubscriptionStatus,
    WebhookEventStatus,
)

type JsonObject = dict[str, Any]
type HistoryKind = Literal["order", "payment", "refund"]


@dataclass(frozen=True)
class ProductRecord:
    id: UUID
    code: str
    kind: str
    plan_key: str | None
    name: str
    description: str | None
    price_paise: int
    currency: str
    interval: str | None
    credits_granted: int
    razorpay_plan_id: str | None
    is_active: bool
    is_sample: bool
    sort_order: int
    features: tuple[str, ...]
    version: int


@dataclass(frozen=True)
class OrderRecord:
    id: UUID
    user_id: UUID
    product_id: UUID
    product_version: int
    kind: str
    amount_paise: int
    currency: str
    credits_granted: int
    status: OrderStatus
    razorpay_order_id: str | None
    subscription_id: UUID | None
    receipt: str
    idempotency_key: str
    failure_reason: str | None
    flagged_at: datetime | None
    flag_reason: str | None
    expires_at: datetime
    paid_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class NewOrder:
    id: UUID
    user_id: UUID
    product: ProductRecord
    idempotency_key: str
    expires_at: datetime
    subscription_id: UUID | None = None


@dataclass(frozen=True)
class OrderView:
    order: OrderRecord
    product_code: str
    product_name: str


@dataclass(frozen=True)
class PaymentRecord:
    id: UUID
    order_id: UUID | None
    subscription_id: UUID | None
    user_id: UUID
    razorpay_payment_id: str
    amount_paise: int
    currency: str
    status: PaymentRecordStatus
    method: str | None
    fee_paise: int | None
    tax_paise: int | None
    credits_granted: int
    refunded_paise: int
    error_code: str | None
    error_description: str | None
    captured_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class NewPayment:
    id: UUID
    order_id: UUID | None
    user_id: UUID
    razorpay_payment_id: str
    amount_paise: int
    currency: str
    status: PaymentRecordStatus
    method: str | None = None
    fee_paise: int | None = None
    tax_paise: int | None = None
    error_code: str | None = None
    error_description: str | None = None
    captured_at: datetime | None = None
    subscription_id: UUID | None = None
    refunded_paise: int = 0


@dataclass(frozen=True)
class SubscriptionRecord:
    id: UUID
    user_id: UUID
    product_id: UUID
    pending_product_id: UUID | None
    razorpay_subscription_id: str | None
    status: SubscriptionStatus
    total_count: int
    paid_count: int
    current_period_start: datetime | None
    current_period_end: datetime | None
    next_charge_at: datetime | None
    cancel_at_period_end: bool
    cancelled_at: datetime | None
    ended_at: datetime | None
    last_event_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class NewSubscription:
    id: UUID
    user_id: UUID
    product_id: UUID
    total_count: int


@dataclass(frozen=True)
class SubscriptionView:
    subscription: SubscriptionRecord
    product: ProductRecord
    pending_product: ProductRecord | None


@dataclass(frozen=True)
class RefundRecord:
    id: UUID
    payment_id: UUID
    razorpay_refund_id: str | None
    amount_paise: int
    status: RefundStatus
    reason: str
    idempotency_key: str
    initiated_by: UUID | None
    credits_clawed_back: int
    failure_reason: str | None
    processed_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class NewRefund:
    id: UUID
    payment_id: UUID
    amount_paise: int
    reason: str
    initiated_by: UUID | None
    idempotency_key: str
    razorpay_refund_id: str | None = None


@dataclass(frozen=True)
class LocalPayment:
    payment: PaymentRecord
    pending_refund_paise: int


@dataclass(frozen=True)
class RunClaim:
    run_id: UUID
    resumed: bool


@dataclass(frozen=True)
class CustomerRecord:
    user_id: UUID
    razorpay_customer_id: str


@dataclass(frozen=True)
class WebhookEventRecord:
    id: UUID
    provider: str
    event_id: str
    event_type: str
    event_created_at: datetime | None
    payload: JsonObject = field(repr=False)
    status: WebhookEventStatus
    attempts: int
    last_error: str | None
    ignored_reason: str | None
    received_at: datetime
    processed_at: datetime | None


@dataclass(frozen=True)
class NewWebhookEvent:
    id: UUID
    provider: str
    event_id: str
    event_type: str
    event_created_at: datetime | None
    payload: JsonObject = field(repr=False)
    received_at: datetime


@dataclass(frozen=True)
class HistoryRow:
    kind: HistoryKind
    id: UUID
    status: str
    amount_paise: int
    currency: str
    title: str
    credits_granted: int | None
    created_at: datetime
    order_id: UUID | None
    payment_id: UUID | None


@dataclass(frozen=True)
class RunCounts:
    checked: int = 0
    repaired: int = 0
    mismatch: int = 0
    errors: int = 0


@dataclass(frozen=True)
class RunOutcome:
    status: RunStatus
    counts: RunCounts
    finished_at: datetime
    summary: JsonObject = field(default_factory=dict[str, Any])
    error: str | None = None
    report_storage_key: str | None = None


@dataclass(frozen=True)
class RequeueQuery:
    provider: str
    stale_before: datetime
    max_attempts: int
    task_name: str
    limit: int


@dataclass(frozen=True)
class SampleProductSpec:
    code: str
    kind: str
    name: str
    description: str
    price_paise: int
    credits_granted: int
    sort_order: int
    features: tuple[str, ...]
    interval: str | None = None
    plan_key: str | None = None
