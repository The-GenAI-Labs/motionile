import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from starlette.types import Receive, Scope, Send
from tests.fakes.resources import make_resources
from tests.fakes.settings import make_settings

from motionile.core.config import AppEnv, BillingSettings, ProvidersMode, Settings
from motionile.modules.billing import RazorpayApi, RazorpayDep, RazorpayNotConfiguredError, razorpay_for
from motionile.modules.billing.razorpay.client import RazorpayClient
from motionile.modules.billing.razorpay.credentials import (
    DEVELOPMENT_KEY_ID,
    DEVELOPMENT_KEY_SECRET,
    DEVELOPMENT_WEBHOOK_SECRET,
    razorpay_credentials,
)
from motionile.modules.billing.razorpay.fake import FakeRazorpay
from motionile.modules.billing.razorpay.fake_delivery import WEBHOOK_PATH, deliver_webhook
from motionile.modules.billing.razorpay.fake_events import BuiltWebhook, WebhookEventName
from motionile.modules.billing.razorpay.fake_store import RedisFakeRazorpayStore

CONFIGURED = BillingSettings(
    razorpay_key_id="rzp_live_configured",
    razorpay_key_secret=SecretStr("configured-key-secret"),
    razorpay_webhook_secret=SecretStr("configured-webhook-secret"),
)


def live_settings(billing: BillingSettings | None = None) -> Settings:
    base = make_settings(AppEnv.LOCAL, providers_mode=ProvidersMode.LIVE)
    return base.model_copy(update={"billing": billing or BillingSettings()})


def test_fake_mode_falls_back_to_development_credentials() -> None:
    credentials = razorpay_credentials(make_settings())

    assert credentials.key_id == DEVELOPMENT_KEY_ID
    assert credentials.webhook_secret.get_secret_value() == DEVELOPMENT_WEBHOOK_SECRET
    assert DEVELOPMENT_KEY_SECRET not in repr(credentials)
    assert DEVELOPMENT_WEBHOOK_SECRET not in repr(credentials)


def test_configured_values_win_over_development_fallbacks() -> None:
    settings = make_settings().model_copy(update={"billing": CONFIGURED})

    credentials = razorpay_credentials(settings)

    assert credentials.key_id == "rzp_live_configured"
    assert credentials.key_secret.get_secret_value() == "configured-key-secret"
    assert credentials.webhook_secret.get_secret_value() == "configured-webhook-secret"


def test_live_mode_requires_every_credential() -> None:
    with pytest.raises(RazorpayNotConfiguredError):
        razorpay_credentials(live_settings())
    partial = BillingSettings(razorpay_key_id="rzp_live_x", razorpay_key_secret=SecretStr("x"))
    with pytest.raises(RazorpayNotConfiguredError):
        razorpay_credentials(live_settings(partial))


def test_fake_mode_builds_the_fake_backed_by_redis_once_per_process() -> None:
    resources = make_resources(make_settings())

    first = razorpay_for(resources)
    second = razorpay_for(resources)

    assert isinstance(first, FakeRazorpay)
    assert first is second
    assert isinstance(first.store, RedisFakeRazorpayStore)
    assert first.store.store is resources.redis_store


def test_live_mode_builds_the_real_client_over_the_razorpay_http_client() -> None:
    resources = make_resources(live_settings(CONFIGURED))

    client = razorpay_for(resources)

    assert isinstance(client, RazorpayClient)
    assert "configured-key-secret" not in repr(client)
    assert razorpay_for(resources) is client


def test_live_mode_without_credentials_fails_when_first_used() -> None:
    resources = make_resources(live_settings())

    with pytest.raises(RazorpayNotConfiguredError):
        razorpay_for(resources)


def test_shared_instances_are_built_once_per_name() -> None:
    resources = make_resources(make_settings())
    calls: list[str] = []

    def build() -> object:
        calls.append("built")
        return object()

    assert resources.shared_instance("thing", build) is resources.shared_instance("thing", build)
    assert resources.shared_instance("other", build) is not resources.shared_instance("thing", build)
    assert calls == ["built", "built"]


async def test_the_dependency_alias_resolves_the_process_wide_instance() -> None:
    resources = make_resources(make_settings())
    application = FastAPI()
    application.state.resources = resources
    seen: list[RazorpayApi] = []

    @application.get("/probe")
    async def probe(razorpay: RazorpayDep) -> dict[str, bool]:
        seen.append(razorpay)
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        await client.get("/probe")
        await client.get("/probe")

    assert len(seen) == 2
    assert seen[0] is seen[1] is razorpay_for(resources)


class RecordingApp:
    def __init__(self, status: int = 202) -> None:
        self.status = status
        self.requests: list[tuple[str, str, bytes, dict[str, str]]] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        headers = {key.decode(): value.decode() for key, value in scope["headers"]}
        self.requests.append((scope["method"], scope["path"], body, headers))
        await send({"type": "http.response.start", "status": self.status, "headers": []})
        await send({"type": "http.response.body", "body": b""})


async def test_delivery_posts_the_exact_signed_bytes_to_the_webhook_path() -> None:
    app = RecordingApp()
    webhook = BuiltWebhook(
        event_id="evt_1",
        event=WebhookEventName.PAYMENT_CAPTURED,
        body=b'{"event":  "payment.captured"}',
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": "abc", "X-Razorpay-Event-Id": "evt_1"},
    )

    statuses = await deliver_webhook(app, webhook, deliveries=3)

    assert statuses == [202, 202, 202]
    assert len(app.requests) == 3
    for method, path, body, headers in app.requests:
        assert (method, path) == ("POST", WEBHOOK_PATH)
        assert body == webhook.body
        assert headers["x-razorpay-signature"] == "abc"
        assert headers["x-razorpay-event-id"] == "evt_1"
        assert headers["content-type"] == "application/json"


async def test_delivery_reports_the_status_of_a_rejecting_application() -> None:
    app = RecordingApp(status=401)
    webhook = BuiltWebhook("evt_2", WebhookEventName.ORDER_PAID, b"{}", {"X-Razorpay-Signature": "bad"})

    assert await deliver_webhook(app, webhook) == [401]


async def test_delivery_to_a_missing_route_is_a_not_found() -> None:
    webhook = BuiltWebhook("evt_3", WebhookEventName.ORDER_PAID, b"{}", {})
    async with httpx.AsyncClient(transport=ASGITransport(app=FastAPI()), base_url="http://test") as probe:
        assert (await probe.post(WEBHOOK_PATH)).status_code == 404

    assert await deliver_webhook(FastAPI(), webhook) == [404]
