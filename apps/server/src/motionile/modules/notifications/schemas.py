from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

BillingTemplateName = Literal[
    "payment_receipt",
    "subscription_activated",
    "renewal_receipt",
    "charge_failed",
    "subscription_halted",
    "cancellation_scheduled",
    "subscription_ended",
    "refund_processed",
    "credits_expiring",
]
BILLING_TEMPLATES: frozenset[str] = frozenset(get_args(BillingTemplateName))
CONTEXT_KEY_LIMIT = 40
CONTEXT_VALUE_LIMIT = 200
CONTEXT_ROW_LIMIT = 12

ContextKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=CONTEXT_KEY_LIMIT)]
ContextValue = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=CONTEXT_VALUE_LIMIT)]

TemplateName = (
    Literal[
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
        "contact_verification",
        "contact_changed",
        "account_deletion",
        "account_restored",
        "data_export_ready",
    ]
    | BillingTemplateName
)


class Notification(BaseModel):
    model_config = ConfigDict(frozen=True)

    destination: str
    channel: Literal["email", "whatsapp"]
    template: TemplateName
    code: str | None = Field(default=None, repr=False)
    link: str | None = Field(default=None, repr=False)
    context: dict[ContextKey, ContextValue] | None = Field(default=None, max_length=CONTEXT_ROW_LIMIT, repr=False)


class RenderedEmail(BaseModel):
    subject: str
    html: str
    text: str
