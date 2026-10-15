from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TemplateName = Literal[
    "verify_contact",
    "login",
    "password_reset",
    "set_password",
    "account_exists",
    "password_changed",
    "new_sign_in",
    "oauth_linked",
    "refresh_reuse",
    "password_lockout",
]


class Notification(BaseModel):
    model_config = ConfigDict(frozen=True)

    destination: str
    channel: Literal["email", "whatsapp"]
    template: TemplateName
    code: str | None = Field(default=None, repr=False)


class RenderedEmail(BaseModel):
    subject: str
    html: str
    text: str
