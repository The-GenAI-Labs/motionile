from dataclasses import dataclass, field

from pydantic import SecretStr

from motionile.core.config import Settings
from motionile.modules.billing.razorpay.exceptions import RazorpayNotConfiguredError

DEVELOPMENT_KEY_ID = "rzp_test_motionile_development"
DEVELOPMENT_KEY_SECRET = "motionile-development-razorpay-key-secret"  # noqa: S105
DEVELOPMENT_WEBHOOK_SECRET = "motionile-development-razorpay-webhook-secret"  # noqa: S105


@dataclass(frozen=True)
class RazorpayCredentials:
    key_id: str
    key_secret: SecretStr = field(repr=False)
    webhook_secret: SecretStr = field(repr=False)


def development_credentials() -> RazorpayCredentials:
    return RazorpayCredentials(
        key_id=DEVELOPMENT_KEY_ID,
        key_secret=SecretStr(DEVELOPMENT_KEY_SECRET),
        webhook_secret=SecretStr(DEVELOPMENT_WEBHOOK_SECRET),
    )


def razorpay_credentials(settings: Settings) -> RazorpayCredentials:
    billing = settings.billing
    fallback = development_credentials() if settings.is_fake_providers else None
    key_id = billing.razorpay_key_id or (fallback.key_id if fallback else None)
    key_secret = billing.razorpay_key_secret or (fallback.key_secret if fallback else None)
    webhook_secret = billing.razorpay_webhook_secret or (fallback.webhook_secret if fallback else None)
    if not key_id or key_secret is None or webhook_secret is None:
        raise RazorpayNotConfiguredError
    return RazorpayCredentials(key_id=key_id, key_secret=key_secret, webhook_secret=webhook_secret)
