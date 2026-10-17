from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import orjson
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from tests.fakes.razorpay import InMemoryFakeRazorpayStore
from tests.fakes.resources import make_resources
from tests.fakes.settings import deployed_settings, make_settings

from motionile.core.config import AppEnv, ProvidersMode
from motionile.core.errors import PROBLEM_MEDIA_TYPE
from motionile.core.resources import Resources
from motionile.entrypoints import api
from motionile.modules.billing import (
    RazorpayBadRequestError,
    RazorpayServerError,
    RazorpayTimeoutError,
    razorpay_for,
    verify_order_payment_signature,
    verify_subscription_payment_signature,
    verify_webhook_signature,
)
from motionile.modules.billing.razorpay.api import PlanParams, PlanPeriod
from motionile.modules.billing.razorpay.credentials import RazorpayCredentials, razorpay_credentials
from motionile.modules.billing.razorpay.factory import FAKE_STORE_KEY
from motionile.scripts.export_openapi import render_openapi

PREFIX = "/v1/_test/razorpay"
PLAN = PlanParams(PlanPeriod.MONTHLY, 1, "Pro", 99_900, "INR")


@dataclass
class Received:
    event_id: str
    event: str
    signature_valid: bool


@dataclass
class Harness:
    client: AsyncClient
    resources: Resources
    store: InMemoryFakeRazorpayStore
    received: list[Received] = field(default_factory=list[Received])

    @property
    def credentials(self) -> RazorpayCredentials:
        return razorpay_credentials(self.resources.settings)

    async def post(self, path: str, body: dict[str, Any] | None = None) -> httpx.Response:
        return await self.client.post(f"{PREFIX}{path}", json=body or {})

    async def order(self, amount: int = 50_000) -> str:
        return (await razorpay_for(self.resources).create_order(amount=amount, currency="INR", receipt="r")).id

    async def active_subscription(self, total_count: int = 3) -> str:
        fake = razorpay_for(self.resources)
        plan = await fake.create_plan(PLAN)
        subscription = await fake.create_subscription(plan_id=plan.id, total_count=total_count)
        authorized = await self.post(f"/subscriptions/{subscription.id}/authorize")
        assert authorized.status_code == 200
        activated = await self.post(f"/subscriptions/{subscription.id}/transition", {"event": "activated"})
        assert activated.status_code == 200
        return subscription.id


def install_receiver(application: FastAPI, harness_received: list[Received], resources: Resources) -> None:
    secret = razorpay_credentials(resources.settings).webhook_secret

    @application.post("/v1/webhooks/razorpay")
    async def receive(request: Request) -> JSONResponse:
        body = await request.body()
        valid = verify_webhook_signature(body, request.headers.get("x-razorpay-signature", ""), secret)
        harness_received.append(Received(request.headers["x-razorpay-event-id"], orjson.loads(body)["event"], valid))
        return JSONResponse({"status": "ok"}, status_code=200 if valid else 401)


@dataclass
class BuiltApp:
    application: FastAPI
    resources: Resources
    received: list[Received]


@pytest.fixture(scope="module")
def built_app() -> BuiltApp:
    settings = make_settings()
    resources = make_resources(settings)
    application = api.create_app(settings, resources=resources)
    received: list[Received] = []
    install_receiver(application, received, resources)
    return BuiltApp(application, resources, received)


@pytest.fixture
async def harness(built_app: BuiltApp) -> AsyncIterator[Harness]:
    store = InMemoryFakeRazorpayStore()
    built_app.resources.shared.clear()
    built_app.resources.shared[FAKE_STORE_KEY] = store
    built_app.received.clear()
    async with AsyncClient(transport=ASGITransport(app=built_app.application), base_url="http://test") as client:
        yield Harness(client, built_app.resources, store, built_app.received)


async def test_paying_an_order_returns_the_signed_checkout_payload_without_emitting_webhooks(harness: Harness) -> None:
    order_id = await harness.order()

    response = await harness.post(f"/orders/{order_id}/pay", {"outcome": "success"})

    body = response.json()
    assert response.status_code == 200
    assert set(body) == {"razorpay_order_id", "razorpay_payment_id", "razorpay_signature", "paymentStatus", "webhooks"}
    assert body["razorpay_order_id"] == order_id
    assert body["paymentStatus"] == "captured"
    assert body["webhooks"] == []
    assert harness.received == []
    assert verify_order_payment_signature(
        order_id, body["razorpay_payment_id"], body["razorpay_signature"], harness.credentials.key_secret
    )
    payment = await razorpay_for(harness.resources).fetch_payment(body["razorpay_payment_id"])
    assert (payment.amount, payment.order_id) == (50_000, order_id)


async def test_paying_can_emit_signed_webhooks_that_the_application_receives(harness: Harness) -> None:
    order_id = await harness.order()

    response = await harness.post(
        f"/orders/{order_id}/pay", {"outcome": "success", "webhooks": ["payment.captured", "order.paid"]}
    )

    emitted = response.json()["webhooks"]
    assert [item["event"] for item in emitted] == ["payment.captured", "order.paid"]
    assert [item["statusCodes"] for item in emitted] == [[200], [200]]
    assert [(item.event, item.signature_valid) for item in harness.received] == [
        ("payment.captured", True),
        ("order.paid", True),
    ]
    assert [item.event_id for item in harness.received] == [item["eventId"] for item in emitted]
    assert len({item["eventId"] for item in emitted}) == 2


async def test_a_failed_payment_has_no_checkout_signature(harness: Harness) -> None:
    order_id = await harness.order()

    response = await harness.post(f"/orders/{order_id}/pay", {"outcome": "failure", "webhooks": ["payment.failed"]})

    body = response.json()
    assert body["razorpay_signature"] is None
    assert body["paymentStatus"] == "failed"
    assert [item.event for item in harness.received] == ["payment.failed"]


async def test_a_custom_amount_simulates_a_mismatch(harness: Harness) -> None:
    order_id = await harness.order(50_000)

    response = await harness.post(
        f"/orders/{order_id}/pay", {"outcome": "success", "amountPaise": 100, "currency": "USD", "method": "upi"}
    )

    payment = await razorpay_for(harness.resources).fetch_payment(response.json()["razorpay_payment_id"])
    assert (payment.amount, payment.currency, payment.method) == (100, "USD", "upi")


async def test_unknown_orders_and_double_payments_are_problems(harness: Harness) -> None:
    missing = await harness.post("/orders/order_missing/pay", {"outcome": "success"})
    order_id = await harness.order()
    await harness.post(f"/orders/{order_id}/pay", {"outcome": "success"})
    again = await harness.post(f"/orders/{order_id}/pay", {"outcome": "success"})

    assert missing.status_code == 404
    assert missing.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert missing.json()["code"] == "fake_razorpay_not_found"
    assert again.status_code == 409
    assert again.json()["code"] == "fake_razorpay_state_conflict"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"outcome": "maybe"},
        {"outcome": "success", "amountPaise": 0},
        {"outcome": "success", "currency": "inr"},
        {"outcome": "success", "unexpected": 1},
        {"outcome": "success", "webhooks": ["payment.exploded"]},
        {"outcome": "success", "webhooks": ["payment.captured"] * 11},
    ],
)
async def test_pay_requests_are_validated(harness: Harness, body: dict[str, Any]) -> None:
    response = await harness.post(f"/orders/{await harness.order()}/pay", body)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"


async def test_identifiers_in_paths_are_validated(harness: Harness) -> None:
    response = await harness.post("/orders/bad%20id/pay", {"outcome": "success"})

    assert response.status_code == 422


async def test_authorizing_a_subscription_returns_the_signed_handler_payload(harness: Harness) -> None:
    fake = razorpay_for(harness.resources)
    plan = await fake.create_plan(PLAN)
    subscription = await fake.create_subscription(plan_id=plan.id, total_count=3)

    response = await harness.post(f"/subscriptions/{subscription.id}/authorize")
    again = await harness.post(f"/subscriptions/{subscription.id}/authorize")

    body = response.json()
    assert set(body) == {
        "razorpay_payment_id",
        "razorpay_subscription_id",
        "razorpay_signature",
        "subscriptionStatus",
        "webhooks",
    }
    assert body["razorpay_subscription_id"] == subscription.id
    assert body["subscriptionStatus"] == "authenticated"
    assert verify_subscription_payment_signature(
        body["razorpay_payment_id"], subscription.id, body["razorpay_signature"], harness.credentials.key_secret
    )
    assert again.status_code == 409
    assert (await fake.fetch_subscription(subscription.id)).status == "authenticated"


async def test_transitions_advance_the_stored_subscription_and_can_emit(harness: Harness) -> None:
    subscription_id = await harness.active_subscription(total_count=3)
    before = await razorpay_for(harness.resources).fetch_subscription(subscription_id)

    response = await harness.post(f"/subscriptions/{subscription_id}/transition", {"event": "charged", "emit": True})

    body = response.json()
    after = await razorpay_for(harness.resources).fetch_subscription(subscription_id)
    assert body["subscriptionStatus"] == "active"
    assert body["paidCount"] == 2
    assert body["razorpayPaymentId"].startswith("pay_")
    assert (after.paid_count, after.current_start) == (2, before.current_end)
    assert [item.event for item in harness.received] == ["subscription.charged"]
    assert body["webhooks"][0]["event"] == "subscription.charged"


async def test_transitions_do_not_emit_unless_asked(harness: Harness) -> None:
    subscription_id = await harness.active_subscription()

    response = await harness.post(f"/subscriptions/{subscription_id}/transition", {"event": "paused"})

    assert response.json()["subscriptionStatus"] == "paused"
    assert response.json()["webhooks"] == []
    assert harness.received == []


async def test_invalid_transitions_are_conflicts(harness: Harness) -> None:
    subscription_id = await harness.active_subscription()

    response = await harness.post(f"/subscriptions/{subscription_id}/transition", {"event": "resumed"})
    unknown = await harness.post("/subscriptions/sub_missing/transition", {"event": "paused"})

    assert response.status_code == 409
    assert unknown.status_code == 404


async def test_transition_delivery_options_are_honoured(harness: Harness) -> None:
    subscription_id = await harness.active_subscription()

    response = await harness.post(
        f"/subscriptions/{subscription_id}/transition",
        {"event": "halted", "emit": True, "eventId": "evt_fixed", "repeat": 3, "validSignature": False},
    )

    assert response.json()["webhooks"][0]["statusCodes"] == [401, 401, 401]
    assert [(item.event_id, item.signature_valid) for item in harness.received] == [("evt_fixed", False)] * 3


async def test_settling_refunds(harness: Harness) -> None:
    fake = razorpay_for(harness.resources)
    order_id = await harness.order()
    paid = await harness.post(f"/orders/{order_id}/pay", {"outcome": "success"})
    refund = await fake.create_refund(paid.json()["razorpay_payment_id"], amount=1_000)

    settled = await harness.post(f"/refunds/{refund.id}/settle", {"outcome": "processed"})
    again = await harness.post(f"/refunds/{refund.id}/settle", {"outcome": "failed"})
    missing = await harness.post("/refunds/rfnd_missing/settle", {"outcome": "failed"})

    assert settled.json() == {"status": "processed"}
    assert (await fake.fetch_refund(refund.id)).status == "processed"
    assert again.status_code == 409
    assert missing.status_code == 404


async def test_delivering_a_webhook_from_current_state(harness: Harness) -> None:
    fake = razorpay_for(harness.resources)
    order_id = await harness.order()
    paid = await harness.post(f"/orders/{order_id}/pay", {"outcome": "success"})
    refund = await fake.create_refund(paid.json()["razorpay_payment_id"], amount=1_000)

    response = await harness.post(
        "/webhooks",
        {"event": "refund.created", "refundId": refund.id, "eventId": "evt_refund_1", "createdAt": 1_700_000_000},
    )

    assert response.json() == {"eventId": "evt_refund_1", "event": "refund.created", "statusCodes": [200]}
    assert harness.received == [Received("evt_refund_1", "refund.created", True)]


async def test_repeated_deliveries_reuse_the_event_id(harness: Harness) -> None:
    order_id = await harness.order()
    paid = await harness.post(f"/orders/{order_id}/pay", {"outcome": "success"})

    response = await harness.post(
        "/webhooks",
        {"event": "payment.captured", "paymentId": paid.json()["razorpay_payment_id"], "repeat": 4},
    )

    assert response.json()["statusCodes"] == [200] * 4
    assert len({item.event_id for item in harness.received}) == 1
    assert len(harness.received) == 4


async def test_invalid_signatures_can_be_requested(harness: Harness) -> None:
    order_id = await harness.order()
    paid = await harness.post(f"/orders/{order_id}/pay", {"outcome": "success"})

    response = await harness.post(
        "/webhooks",
        {"event": "payment.captured", "paymentId": paid.json()["razorpay_payment_id"], "validSignature": False},
    )

    assert response.json()["statusCodes"] == [401]
    assert [item.signature_valid for item in harness.received] == [False]


async def test_webhooks_need_their_entities(harness: Harness) -> None:
    missing_reference = await harness.post("/webhooks", {"event": "payment.captured"})
    unknown = await harness.post("/webhooks", {"event": "payment.captured", "paymentId": "pay_missing"})
    out_of_range = await harness.post("/webhooks", {"event": "payment.captured", "repeat": 21})

    assert missing_reference.status_code == 422
    assert missing_reference.json()["code"] == "fake_razorpay_missing_entity"
    assert unknown.status_code == 404
    assert out_of_range.status_code == 422


async def test_faults_and_reset(harness: Harness) -> None:
    fake = razorpay_for(harness.resources)

    armed = await harness.post("/faults", {"operation": "create_order", "kind": "server_error", "count": 2})
    with pytest.raises(RazorpayServerError):
        await fake.create_order(amount=500, currency="INR", receipt="a")
    rejected = await harness.post("/faults", {"operation": "nonsense", "kind": "server_error"})
    reset = await harness.post("/reset")

    assert armed.json() == {"status": "armed"}
    assert rejected.status_code == 422
    assert reset.json() == {"status": "reset"}
    assert (await fake.create_order(amount=500, currency="INR", receipt="a")).receipt == "a"
    with pytest.raises(RazorpayBadRequestError):
        await fake.create_order(amount=1, currency="INR", receipt="b")


async def test_timeout_after_create_fault_through_the_route_leaves_the_order(harness: Harness) -> None:
    fake = razorpay_for(harness.resources)
    await harness.post("/faults", {"operation": "create_order", "kind": "timeout_after_create"})

    with pytest.raises(RazorpayTimeoutError, match="outcome is unknown"):
        await fake.create_order(amount=500, currency="INR", receipt="kept")

    assert await fake.find_order_by_receipt("kept") is not None
    await harness.post("/reset")
    assert await fake.find_order_by_receipt("kept") is None


async def test_routes_answer_not_found_when_providers_are_live() -> None:
    settings = make_settings(providers_mode=ProvidersMode.LIVE)
    resources = make_resources(settings)
    application = api.create_app(settings, resources=resources)

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        response = await client.post(f"{PREFIX}/reset", json={})

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


@pytest.mark.parametrize("env", [AppEnv.LOCAL, AppEnv.CI])
async def test_routes_are_mounted_in_local_and_ci(env: AppEnv) -> None:
    settings = make_settings(env)
    application = api.create_app(settings, resources=make_resources(settings))

    paths = set(application.openapi()["paths"])

    assert f"{PREFIX}/reset" in paths
    assert f"{PREFIX}/webhooks" in paths
    assert f"{PREFIX}/orders/{{razorpayOrderId}}/pay" in paths
    assert f"{PREFIX}/subscriptions/{{razorpaySubscriptionId}}/authorize" in paths
    assert f"{PREFIX}/subscriptions/{{razorpaySubscriptionId}}/transition" in paths
    assert f"{PREFIX}/refunds/{{razorpayRefundId}}/settle" in paths


@pytest.mark.parametrize("env", [AppEnv.STAGING, AppEnv.PRODUCTION])
async def test_routes_are_absent_when_deployed(env: AppEnv) -> None:
    settings = deployed_settings(env)
    application = api.create_app(settings, resources=make_resources(settings))

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        response = await client.post(f"{PREFIX}/reset", json={})

    assert response.status_code == 404
    assert not any("razorpay" in path.lower() and "_test" in path for path in application.openapi()["paths"])


async def test_routes_are_absent_when_test_routes_are_excluded_and_from_the_contract() -> None:
    settings = make_settings()
    application = api.create_app(settings, resources=make_resources(settings), include_test_routes=False)

    assert not any(path.startswith("/v1/_test") for path in application.openapi()["paths"])
    assert "/v1/_test" not in render_openapi()


async def test_routes_cannot_be_forced_on_when_deployed() -> None:
    settings = deployed_settings()
    application = api.create_app(settings, resources=make_resources(settings), include_test_routes=True)

    assert not any(path.startswith("/v1/_test") for path in application.openapi()["paths"])
