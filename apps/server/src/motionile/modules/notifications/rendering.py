from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from motionile.modules.notifications.schemas import BILLING_TEMPLATES, Notification, RenderedEmail, TemplateName

TEMPLATES: dict[TemplateName, tuple[str, str]] = {
    "verify_contact": ("Verify your contact", "Use this code to activate your Motionile account."),
    "login": ("Your sign-in code", "Use this code to sign in to Motionile."),
    "password_reset": ("Reset your password", "Use this code to reset your Motionile password."),
    "set_password": ("Set your password", "Use this code to add a password to your Motionile account."),
    "account_exists": ("Your Motionile account", "You already have an account. Sign in or request a password reset."),
    "password_changed": ("Password changed", "Your Motionile password was changed."),
    "new_sign_in": ("New sign-in", "Your Motionile account was accessed from a new device."),
    "oauth_linked": ("Sign-in provider linked", "A sign-in provider was linked to your Motionile account."),
    "refresh_reuse": ("Session secured", "Suspicious session reuse was detected. That session has been revoked."),
    "password_lockout": (
        "Password sign-in temporarily locked",
        "Repeated failed password attempts temporarily locked password sign-in. You can still sign in using an OTP.",
    ),
    "contact_verification": ("Verify your contact", "Use this code to verify your new Motionile contact."),
    "contact_changed": ("Contact details changed", "Your Motionile contact details were changed."),
    "account_deletion": ("Confirm account deletion", "Use this code to confirm deletion of your Motionile account."),
    "account_restored": ("Account restored", "Your Motionile account was restored."),
    "data_export_ready": ("Your data export is ready", "Your Motionile data export is ready for 24 hours."),
    "payment_receipt": ("Payment received", "Thank you. We received your payment and added your credits."),
    "subscription_activated": (
        "Subscription active",
        "Your Motionile subscription is active and the credits for this period were added.",
    ),
    "renewal_receipt": (
        "Subscription renewed",
        "Your Motionile subscription renewed and the credits for the new period were added.",
    ),
    "charge_failed": (
        "Payment failed",
        "We could not charge your payment method for your Motionile subscription. We will try again. "
        "Update your payment method to avoid an interruption.",
    ),
    "subscription_halted": (
        "Subscription paused",
        "Your Motionile subscription was paused after repeated failed payments. Start a new subscription to continue.",
    ),
    "cancellation_scheduled": (
        "Cancellation scheduled",
        "Your Motionile subscription will end at the close of the current billing period. "
        "Your credits stay available until they expire.",
    ),
    "subscription_ended": (
        "Subscription ended",
        "Your Motionile subscription has ended. Credits you already own stay available until they expire.",
    ),
    "refund_processed": (
        "Refund processed",
        "Your refund was processed. It reaches your original payment method in a few business days.",
    ),
    "credits_expiring": (
        "Credits expiring soon",
        "Some of your Motionile credits will expire soon. Use them before the date below.",
    ),
}
ENVIRONMENT = Environment(
    loader=FileSystemLoader(Path(__file__).with_name("templates")),
    autoescape=select_autoescape(default=True),
    undefined=StrictUndefined,
)


def detail_rows(notification: Notification) -> list[tuple[str, str]]:
    return [(key.replace("_", " ").capitalize(), value) for key, value in (notification.context or {}).items()]


def render_email(notification: Notification) -> RenderedEmail:
    subject, message = TEMPLATES[notification.template]
    values = {
        "subject": subject,
        "message": message,
        "code": notification.code,
        "link": notification.link,
        "details": detail_rows(notification),
        "security_notice": notification.template not in BILLING_TEMPLATES,
    }
    return RenderedEmail(
        subject=f"{subject} · Motionile",
        html=ENVIRONMENT.get_template("message.html.jinja").render(values),
        text=ENVIRONMENT.get_template("message.txt.jinja").render(values),
    )
