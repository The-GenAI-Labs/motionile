from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from motionile.modules.notifications.schemas import Notification, RenderedEmail, TemplateName

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
}
ENVIRONMENT = Environment(
    loader=FileSystemLoader(Path(__file__).with_name("templates")),
    autoescape=select_autoescape(default=True),
    undefined=StrictUndefined,
)


def render_email(notification: Notification) -> RenderedEmail:
    subject, message = TEMPLATES[notification.template]
    values = {"subject": subject, "message": message, "code": notification.code}
    return RenderedEmail(
        subject=f"{subject} · Motionile",
        html=ENVIRONMENT.get_template("message.html.jinja").render(values),
        text=ENVIRONMENT.get_template("message.txt.jinja").render(values),
    )
