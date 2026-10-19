from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID

from motionile.modules.billing.records import (
    JsonObject,
    OrderRecord,
    PaymentRecord,
    ProductRecord,
    RefundRecord,
    SubscriptionRecord,
)
from motionile.modules.billing.states import (
    OrderStatus,
    PaymentRecordStatus,
    RefundStatus,
    RunStatus,
    SubscriptionStatus,
    WebhookEventStatus,
)
from motionile.modules.credits import LotRecord


@dataclass(frozen=True)
class RecordPage[ItemT]:
    items: list[ItemT]
    next_cursor: str | None


@dataclass(frozen=True)
class ProductRow:
    record: ProductRecord
    is_used: bool
    supersedes_product_id: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ProductFilter:
    kind: str | None = None
    is_active: bool | None = None
    is_sample: bool | None = None
    search: str | None = None


@dataclass(frozen=True)
class ProductLink:
    id: UUID
    code: str
    name: str
    version: int


@dataclass(frozen=True)
class ProductLinks:
    supersedes: ProductLink | None
    superseded_by: tuple[ProductLink, ...]


@dataclass(frozen=True)
class NewProduct:
    id: UUID
    code: str
    kind: str
    name: str
    price_paise: int
    credits_granted: int
    plan_key: str | None = None
    description: str | None = None
    currency: str = "INR"
    interval: str | None = None
    is_active: bool = False
    is_sample: bool = False
    sort_order: int = 0
    features: tuple[str, ...] = ()
    version: int = 1
    supersedes_product_id: UUID | None = None


@dataclass(frozen=True)
class ProductDetail:
    row: ProductRow
    links: ProductLinks


@dataclass(frozen=True)
class PaymentFilter:
    status: PaymentRecordStatus | None = None
    user_id: UUID | None = None
    order_id: UUID | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    flagged: bool | None = None


@dataclass(frozen=True)
class PaymentRow:
    payment: PaymentRecord
    product_code: str | None
    product_name: str | None
    flagged: bool


@dataclass(frozen=True)
class OrderFilter:
    status: OrderStatus | None = None
    flagged: bool | None = None
    user_id: UUID | None = None


@dataclass(frozen=True)
class OrderRow:
    order: OrderRecord
    product_code: str
    product_name: str


@dataclass(frozen=True)
class RefundFilter:
    status: RefundStatus | None = None
    payment_id: UUID | None = None


@dataclass(frozen=True)
class RefundRow:
    refund: RefundRecord
    user_id: UUID
    payment_amount_paise: int
    currency: str


@dataclass(frozen=True)
class SubscriptionFilter:
    status: SubscriptionStatus | None = None
    product_id: UUID | None = None
    plan_key: str | None = None
    user_id: UUID | None = None


@dataclass(frozen=True)
class SubscriptionRow:
    subscription: SubscriptionRecord
    product: ProductRecord
    pending_product: ProductRecord | None


@dataclass(frozen=True)
class PaymentDetail:
    row: PaymentRow
    order: OrderRow | None
    subscription: SubscriptionRow | None
    refunds: list[RefundRecord]
    lot: LotRecord | None
    refundable_paise: int
    pending_refund_paise: int
    preview_amount_paise: int
    credits_to_claw_back: int


@dataclass(frozen=True)
class EventFilter:
    status: WebhookEventStatus | None = None
    event_type: str | None = None
    received_from: datetime | None = None
    received_to: datetime | None = None


@dataclass(frozen=True)
class EventSummary:
    id: UUID
    provider: str
    event_id: str
    event_type: str
    event_created_at: datetime | None
    status: WebhookEventStatus
    attempts: int
    last_error: str | None
    ignored_reason: str | None
    received_at: datetime
    processed_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class EventDetail:
    summary: EventSummary
    payload: JsonObject = field(repr=False)


@dataclass(frozen=True)
class RunFilter:
    type: str | None = None
    status: RunStatus | None = None
    has_mismatches: bool | None = None


@dataclass(frozen=True)
class RunRow:
    id: UUID
    type: str
    status: RunStatus
    period_start: datetime | None
    period_end: datetime | None
    checked_count: int
    repaired_count: int
    mismatch_count: int
    summary: JsonObject
    report_storage_key: str | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class RevenueDay:
    day: date
    captured_paise: int
    refunded_paise: int
    payment_count: int


@dataclass(frozen=True)
class PlanCount:
    plan_key: str | None
    product_code: str
    product_name: str
    interval: str | None
    live_count: int
    active_count: int


@dataclass(frozen=True)
class SubscriptionCounts:
    by_plan: tuple[PlanCount, ...]
    by_status: Mapping[str, int]
