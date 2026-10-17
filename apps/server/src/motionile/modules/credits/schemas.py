from datetime import date, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from motionile.core.schemas import CursorPage, PageQuery, ResponseModel

type LotSourceName = Literal["purchase", "subscription", "admin", "promo"]
type LedgerReasonName = Literal[
    "purchase",
    "subscription_grant",
    "promo_grant",
    "admin_adjust",
    "reserve",
    "commit",
    "release",
    "refund_clawback",
    "expiry",
]
type LedgerRefTypeName = Literal["payment", "refund", "reservation", "lot", "admin", "promo"]


class ExpiringLotResponse(ResponseModel):
    source: LotSourceName
    remaining: int
    expires_at: datetime


class WalletResponse(ResponseModel):
    balance: int
    reserved: int
    available: int
    expiring_soon: list[ExpiringLotResponse]


class LedgerEntryResponse(ResponseModel):
    id: UUID
    reason: LedgerReasonName
    delta: int
    reserved_delta: int
    balance_after: int
    reserved_after: int
    ref_type: LedgerRefTypeName | None
    ref_id: UUID | None
    created_at: datetime


class UsageEntryResponse(ResponseModel):
    id: UUID
    stage: str
    credits: int
    job_id: UUID | None
    publication_id: UUID | None
    created_at: datetime


class DailyUsageResponse(ResponseModel):
    date: date
    credits: int
    records: int


class DailyUsageListResponse(ResponseModel):
    items: list[DailyUsageResponse]


class LedgerPageResponse(CursorPage[LedgerEntryResponse]):
    pass


class UsagePageResponse(CursorPage[UsageEntryResponse]):
    pass


class UsageQuery(PageQuery):
    aggregate: Literal["daily"] | None = None
    range_start: date | None = Field(default=None, alias="from")
    range_end: date | None = Field(default=None, alias="to")

    @model_validator(mode="after")
    def require_aggregate_for_range(self) -> Self:
        if self.aggregate is None and (self.range_start is not None or self.range_end is not None):
            message = "from and to require aggregate=daily"
            raise ValueError(message)
        return self
