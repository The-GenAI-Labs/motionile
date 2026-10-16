from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from motionile.core.schemas import CursorPage, PageQuery, ResponseModel, StrictModel


class UserContactResponse(ResponseModel):
    id: UUID
    kind: Literal["email", "phone"]
    value: str
    verified: bool
    primary: bool


class UserProfileResponse(ResponseModel):
    id: UUID
    name: str | None
    status: str
    locale: str
    avatar_url: str | None
    contacts: list[UserContactResponse]
    created_at: datetime


class UserProfileUpdateRequest(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    locale: str | None = Field(default=None, pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$")

    @model_validator(mode="after")
    def has_update(self) -> "UserProfileUpdateRequest":
        if self.name is None and self.locale is None:
            raise ValueError("At least one profile field is required.")
        return self


class AvatarResponse(ResponseModel):
    url: str


class ContactAddRequest(StrictModel):
    identifier: str = Field(min_length=3, max_length=254)


class ContactChallengeResponse(ResponseModel):
    challenge_token: str
    destination: str
    channel: Literal["email", "whatsapp"]
    expires_in: int = 300
    resend_after: int = 60


class ContactVerifyRequest(StrictModel):
    challenge_token: str = Field(min_length=20, max_length=128)
    code: str = Field(pattern=r"^[0-9]{6}$")


class UserPreferencesResponse(ResponseModel):
    default_style: str | None
    pace: str
    language: str
    depth: str
    default_voice_id: UUID | None
    default_aspect: str
    captions_enabled: bool


class UserPreferencesUpdateRequest(StrictModel):
    default_style: str | None = Field(default=None, max_length=80, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    pace: str = Field(max_length=32)
    language: str = Field(max_length=20)
    depth: str = Field(max_length=32)
    default_voice_id: None = None
    default_aspect: str = Field(max_length=10)
    captions_enabled: bool


class ExportResponse(ResponseModel):
    status: Literal["queued"] = "queued"


class AccountDeletionConfirmRequest(ContactVerifyRequest):
    pass


class AdminUserQuery(PageQuery):
    search: str | None = Field(default=None, max_length=120)
    status: Literal["pending_verification", "active", "suspended", "deleted"] | None = None
    role: str | None = Field(default=None, max_length=40)
    created_from: datetime | None = None
    created_to: datetime | None = None
    sort: Literal["created_desc", "created_asc"] = "created_desc"


class AdminUserSummary(ResponseModel):
    id: UUID
    name: str | None
    status: str
    primary_contact: str | None
    roles: list[str]
    created_at: datetime


class AdminUserListResponse(CursorPage[AdminUserSummary]):
    pass


class AdminUserAuditEntry(ResponseModel):
    id: UUID
    action: str
    actor_type: str
    target_type: str | None
    target_id: str | None
    created_at: datetime


class AdminUserDetailResponse(UserProfileResponse):
    roles: list[str]
    active_session_count: int
    recent_audit: list[AdminUserAuditEntry]


class UserRoleMutationRequest(StrictModel):
    role_id: UUID
