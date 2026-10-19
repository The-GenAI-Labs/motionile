from datetime import date, datetime
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator

from motionile.core.schemas import CursorPage, ResponseModel, StrictModel
from motionile.modules.billing.admin_schemas import AdminLotResponse

MAX_ADJUSTMENT = 1_000_000
MAX_REASON_LENGTH = 500


class AdjustCreditsRequest(StrictModel):
    delta: int = Field(ge=-MAX_ADJUSTMENT, le=MAX_ADJUSTMENT)
    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)
    expires_at: AwareDatetime | None = None

    @field_validator("delta")
    @classmethod
    def reject_zero(cls, value: int) -> int:
        if value == 0:
            message = "delta must not be zero"
            raise ValueError(message)
        return value


class AdjustCreditsResponse(ResponseModel):
    user_id: UUID
    delta: int
    action_id: UUID
    lot_id: UUID | None
    balance_after: int


class AdminUserCreditsResponse(ResponseModel):
    user_id: UUID
    balance: int
    reserved: int
    available: int
    lots: list[AdminLotResponse]
    next_cursor: str | None = Field(
        default=None, description="Opaque cursor for the next page of lots; null on the last page"
    )


class AdminLedgerEntryResponse(ResponseModel):
    id: UUID
    reason: str
    delta: int
    reserved_delta: int
    balance_after: int
    reserved_after: int
    ref_type: str | None
    ref_id: UUID | None
    idempotency_key: str
    metadata: dict[str, object]
    created_at: datetime


class AdminLedgerPageResponse(CursorPage[AdminLedgerEntryResponse]):
    pass


class AnalyticsQuery(StrictModel):
    range_start: date | None = Field(default=None, alias="from")
    range_end: date | None = Field(default=None, alias="to")


class RevenueDayResponse(ResponseModel):
    date: date
    captured_paise: int
    refunded_paise: int
    net_paise: int
    payment_count: int


class RevenueDayTotalsResponse(ResponseModel):
    captured_paise: int
    refunded_paise: int
    net_paise: int
    payment_count: int


class RevenueAnalyticsResponse(ResponseModel):
    range_start: date
    range_end: date
    currency: str
    days: list[RevenueDayResponse]
    totals: RevenueDayTotalsResponse


class PlanCountResponse(ResponseModel):
    plan_key: str | None
    product_code: str
    product_name: str
    interval: str | None
    live_count: int
    active_count: int


class SubscriptionAnalyticsResponse(ResponseModel):
    total_live: int
    total_active: int
    by_plan: list[PlanCountResponse]
    by_status: dict[str, int]


class CreditsGrantedResponse(ResponseModel):
    purchase: int
    subscription: int
    promo: int
    admin: int


class CreditsDayResponse(ResponseModel):
    date: date
    granted: CreditsGrantedResponse
    granted_total: int
    consumed: int
    expired: int
    clawed_back: int
    adjusted_down: int


class CreditsTotalsResponse(ResponseModel):
    granted: CreditsGrantedResponse
    granted_total: int
    consumed: int
    expired: int
    clawed_back: int
    adjusted_down: int


class CreditsAnalyticsResponse(ResponseModel):
    range_start: date
    range_end: date
    days: list[CreditsDayResponse]
    totals: CreditsTotalsResponse
    wallets: int
    balance: int
    reserved: int
