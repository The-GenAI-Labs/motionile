from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, SecretStr, model_validator

from motionile.core.schemas import ResponseModel, StrictModel

Password = Annotated[SecretStr, Field(min_length=10, max_length=128)]
Code = Annotated[str, Field(pattern=r"^[0-9]{6}$")]


class RegisterRequest(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    email: str | None = Field(default=None, min_length=3, max_length=254)
    phone: str | None = Field(default=None, min_length=7, max_length=32)
    password: Password

    @model_validator(mode="after")
    def exactly_one_contact(self) -> Self:
        if (self.email is None) == (self.phone is None):
            raise ValueError("Supply exactly one email or phone number.")
        return self


class IdentifierRequest(StrictModel):
    identifier: str = Field(min_length=3, max_length=254)


class LoginRequest(IdentifierRequest):
    password: Annotated[SecretStr, Field(min_length=1, max_length=128)]


class CodeRequest(StrictModel):
    code: Code


class ResetPasswordRequest(CodeRequest):
    new_password: Password


class ChangePasswordRequest(StrictModel):
    current_password: Annotated[SecretStr, Field(min_length=1, max_length=128)]
    new_password: Password


class ChallengeResponse(ResponseModel):
    destination: str
    channel: Literal["email", "whatsapp"]
    expires_in: int = 300
    resend_after: int = 60


class ContactResponse(ResponseModel):
    kind: str
    destination: str
    verified: bool
    primary: bool


class SessionUser(ResponseModel):
    id: UUID
    name: str | None
    status: str
    roles: list[str]
    contacts: list[ContactResponse]
    has_password: bool
    linked_providers: list[str]


class SessionResponse(ResponseModel):
    id: UUID
    device_label: str | None
    ip: str | None
    created_at: datetime
    last_used_at: datetime
    current: bool


class SessionsResponse(ResponseModel):
    items: list[SessionResponse]
    next_cursor: str | None = None


class JwksResponse(ResponseModel):
    keys: list[dict[str, str]]


class OAuthStartQuery(StrictModel):
    next: str = Field(default="/dashboard", max_length=1024)
    intent: Literal["login", "link"] = "login"


class OAuthCallbackQuery(StrictModel):
    state: str = Field(default="", max_length=256)
    code: str = Field(default="", max_length=2048)
    error: str | None = Field(default=None, max_length=128)
    error_description: str | None = Field(default=None, max_length=1024, validation_alias="error_description")
    error_uri: str | None = Field(default=None, max_length=2048, validation_alias="error_uri")
    scope: str | None = Field(default=None, max_length=2048)
    authuser: str | None = Field(default=None, max_length=32)
    prompt: str | None = Field(default=None, max_length=128)
    session_state: str | None = Field(default=None, max_length=256, validation_alias="session_state")


class SessionListQuery(StrictModel):
    cursor: str | None = Field(default=None, max_length=512)
    limit: int = Field(default=20, ge=1, le=100)
