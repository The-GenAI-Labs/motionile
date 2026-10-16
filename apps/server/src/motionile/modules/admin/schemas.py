from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from motionile.core.schemas import CursorPage, PageQuery, ResponseModel


class AuditQuery(PageQuery):
    actor_user_id: UUID | None = None
    action: str | None = Field(default=None, max_length=100)
    target_type: str | None = Field(default=None, max_length=64)
    target_id: str | None = Field(default=None, max_length=128)
    created_from: datetime | None = None
    created_to: datetime | None = None


class AuditEntryResponse(ResponseModel):
    id: UUID
    actor_user_id: UUID | None
    actor_type: str
    action: str
    target_type: str | None
    target_id: str | None
    ip: str | None
    user_agent: str | None
    request_id: str | None
    metadata: dict[str, Any]
    created_at: datetime


class AuditListResponse(CursorPage[AuditEntryResponse]):
    pass


class DailyUsers(ResponseModel):
    date: date
    count: int


class AnalyticsResponse(ResponseModel):
    total_users: int
    verified_ratio: float
    active_sessions: int
    new_users: list[DailyUsers]
    sign_in_methods: dict[str, int]
