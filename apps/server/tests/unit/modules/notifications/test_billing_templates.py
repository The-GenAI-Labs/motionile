import base64
from collections.abc import AsyncIterator, Mapping
from typing import get_args

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.resources import make_resources
from tests.fakes.settings import make_settings

from motionile.core.resources import Resources
from motionile.core.security.encryption import EncryptedValue
from motionile.modules.notifications import BillingTemplateName, Notification, enqueue_billing_email
from motionile.modules.notifications import queue as queue_module
from motionile.modules.notifications.rendering import TEMPLATES, render_email
from motionile.modules.notifications.schemas import BILLING_TEMPLATES, CONTEXT_ROW_LIMIT

BILLING_NAMES: tuple[BillingTemplateName, ...] = get_args(BillingTemplateName)
EXPECTED_NAMES = {
    "payment_receipt",
    "subscription_activated",
    "renewal_receipt",
    "charge_failed",
    "subscription_halted",
    "cancellation_scheduled",
    "subscription_ended",
    "refund_processed",
    "credits_expiring",
}
CONTEXT = {"credits": "120", "expires_on": "24 October 2026"}


def billing_notification(template: BillingTemplateName, context: Mapping[str, str] | None = None) -> Notification:
    return Notification(
        destination="user@example.com",
        channel="email",
        template=template,
        context=dict(context) if context is not None else None,
    )


@pytest.fixture
async def resources() -> AsyncIterator[Resources]:
    built = make_resources(make_settings())
    yield built
    await built.aclose()


def test_every_billing_template_has_a_subject_and_message() -> None:
    assert set(BILLING_NAMES) == EXPECTED_NAMES
    assert EXPECTED_NAMES == BILLING_TEMPLATES
    for name in BILLING_NAMES:
        subject, message = TEMPLATES[name]
        assert subject
        assert message.endswith(".")


@pytest.mark.parametrize("template", BILLING_NAMES)
def test_billing_templates_render_html_and_text_with_a_details_table(template: BillingTemplateName) -> None:
    subject, message = TEMPLATES[template]

    rendered = render_email(billing_notification(template, CONTEXT))

    assert rendered.subject == f"{subject} · Motionile"
    assert subject in rendered.html
    assert message in rendered.html
    assert "<table" in rendered.html
    assert ">Credits</th>" in rendered.html
    assert ">120</td>" in rendered.html
    assert ">Expires on</th>" in rendered.html
    assert ">24 October 2026</td>" in rendered.html
    assert "Motionile" in rendered.html
    assert "secure your account" not in rendered.html
    assert rendered.text.startswith(subject)
    assert message in rendered.text
    assert "Credits: 120" in rendered.text
    assert "Expires on: 24 October 2026" in rendered.text
    assert rendered.text.rstrip().endswith("Motionile")
    assert "secure your account" not in rendered.text


@pytest.mark.parametrize("template", BILLING_NAMES)
def test_billing_templates_render_without_context(template: BillingTemplateName) -> None:
    rendered = render_email(billing_notification(template))

    assert "<table" not in rendered.html
    assert TEMPLATES[template][1] in rendered.text


def test_details_are_escaped_in_html_and_keep_their_order() -> None:
    rendered = render_email(
        billing_notification("payment_receipt", {"plan": "<b>Pro</b>", "amount": "Rs 499", "receipt_no": "A&B"})
    )

    assert "<b>Pro</b>" not in rendered.html
    assert "&lt;b&gt;Pro&lt;/b&gt;" in rendered.html
    assert "A&amp;B" in rendered.html
    assert rendered.html.index(">Plan<") < rendered.html.index(">Amount<") < rendered.html.index(">Receipt no<")
    assert rendered.text.index("Plan:") < rendered.text.index("Amount:") < rendered.text.index("Receipt no:")


def test_html_stays_readable_in_light_and_dark_schemes() -> None:
    html = render_email(billing_notification("renewal_receipt", CONTEXT)).html

    assert 'name="color-scheme" content="light dark"' in html
    assert "border-top:1px solid" in html
    assert "#" not in html.replace("&#", "")


def test_existing_templates_keep_their_security_notice_and_have_no_table() -> None:
    rendered = render_email(Notification(destination="a@b.co", channel="email", template="login", code="123456"))

    assert "If you did not request this, secure your account or contact support." in rendered.html
    assert "If you did not request this, secure your account or contact support." in rendered.text
    assert "<table" not in rendered.html


def test_context_is_bounded_and_stripped() -> None:
    notification = billing_notification("payment_receipt", {"  amount  ": "  Rs 499  "})
    assert notification.context == {"amount": "Rs 499"}

    with pytest.raises(ValidationError):
        billing_notification("payment_receipt", {f"key{index}": "value" for index in range(CONTEXT_ROW_LIMIT + 1)})
    with pytest.raises(ValidationError):
        billing_notification("payment_receipt", {"k" * 41: "value"})
    with pytest.raises(ValidationError):
        billing_notification("payment_receipt", {"key": "v" * 201})
    with pytest.raises(ValidationError):
        billing_notification("payment_receipt", {"key": " "})


def test_context_never_appears_in_the_notification_repr() -> None:
    assert "120" not in repr(billing_notification("credits_expiring", CONTEXT))


def test_unknown_templates_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Notification.model_validate({"destination": "a@b.co", "channel": "email", "template": "invoice"})


async def test_billing_helper_queues_an_encrypted_email_after_commit(
    resources: Resources, monkeypatch: pytest.MonkeyPatch
) -> None:
    queued: list[dict[str, object]] = []

    def capture(session: AsyncSession, registered: object, *, priority: int = 0, **arguments: object) -> None:
        del session, registered
        queued.append({"priority": priority, **arguments})

    monkeypatch.setattr(queue_module, "defer_after_commit", capture)
    session = AsyncSession()

    enqueue_billing_email(resources, session, email="user@example.com", template="credits_expiring", context=CONTEXT)

    await session.close()
    assert len(queued) == 1
    job = queued[0]
    decrypted = resources.key_ring.decrypt(
        EncryptedValue(
            ciphertext=base64.b64decode(str(job["ciphertext"])),
            nonce=base64.b64decode(str(job["nonce"])),
            key_version=int(str(job["key_version"])),
        ),
        associated_data=queue_module.NOTIFICATION_AAD,
    )
    message = Notification.model_validate_json(decrypted)
    assert (message.destination, message.channel, message.template) == ("user@example.com", "email", "credits_expiring")
    assert message.context == CONTEXT
    assert job["priority"] == 0
