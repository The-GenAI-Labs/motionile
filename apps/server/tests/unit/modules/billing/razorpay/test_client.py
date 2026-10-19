import base64
import ipaddress
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
import orjson
import pytest
from pydantic import SecretStr
from structlog.testing import capture_logs

from motionile.core.config import OutboundHttpSettings
from motionile.core.http.safe_client import IPAddress, OutboundRequestBlockedError, SafeHttpClient
from motionile.modules.billing import (
    RazorpayAuthenticationError,
    RazorpayBadRequestError,
    RazorpayNotFoundError,
    RazorpayRateLimitedError,
    RazorpayResponseError,
    RazorpayServerError,
    RazorpayTimeoutError,
)
from motionile.modules.billing.razorpay.api import PlanParams, PlanPeriod, ScheduleChangeAt
from motionile.modules.billing.razorpay.client import RazorpayClient, RetryPolicy
from motionile.modules.billing.razorpay.credentials import RazorpayCredentials
from motionile.modules.billing.razorpay.exceptions import (
    RazorpayError,
    RazorpayInvalidIdentifierError,
    RazorpayUnexpectedStatusError,
)

BASE_URL = "https://api.razorpay.com"
KEY_ID = "rzp_test_abc123"
KEY_SECRET = "super-secret-key-value"  # noqa: S105
CREDENTIALS = RazorpayCredentials(KEY_ID, SecretStr(KEY_SECRET), SecretStr("webhook-secret-value"))
EXPECTED_AUTHORIZATION = "Basic " + base64.b64encode(f"{KEY_ID}:{KEY_SECRET}".encode()).decode()
CREATED_AT = 1_760_000_000

ORDER: dict[str, object] = {
    "id": "order_Abc123",
    "entity": "order",
    "amount": 49900,
    "amount_paid": 0,
    "amount_due": 49900,
    "currency": "INR",
    "receipt": "rcpt_1",
    "status": "created",
    "attempts": 0,
    "notes": [],
    "created_at": CREATED_AT,
    "unknown_future_field": {"a": 1},
}
PAYMENT: dict[str, object] = {
    "id": "pay_Abc123",
    "entity": "payment",
    "amount": 49900,
    "currency": "INR",
    "status": "captured",
    "order_id": "order_Abc123",
    "method": "card",
    "captured": True,
    "amount_refunded": 0,
    "fee": 1180,
    "tax": 180,
    "notes": {"orderId": "o-1"},
    "created_at": CREATED_AT,
}
SUBSCRIPTION: dict[str, object] = {
    "id": "sub_Abc123",
    "entity": "subscription",
    "plan_id": "plan_Abc123",
    "customer_id": None,
    "status": "active",
    "current_start": CREATED_AT,
    "current_end": CREATED_AT + 2_592_000,
    "ended_at": None,
    "charge_at": CREATED_AT + 2_592_000,
    "total_count": 12,
    "paid_count": 1,
    "remaining_count": "11",
    "has_scheduled_changes": False,
    "notes": {},
    "created_at": CREATED_AT,
}
REFUND: dict[str, object] = {
    "id": "rfnd_Abc123",
    "entity": "refund",
    "payment_id": "pay_Abc123",
    "amount": 1000,
    "currency": "INR",
    "status": "pending",
    "notes": {"refundId": "r-1"},
    "created_at": CREATED_AT,
}


async def public_dns(_host: str, _port: int) -> list[IPAddress]:
    return [ipaddress.ip_address("104.18.0.1")]


@dataclass
class Script:
    responses: list[httpx.Response | Exception]
    requests: list[httpx.Request] = field(default_factory=list[httpx.Request])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    @property
    def last_body(self) -> dict[str, object]:
        body: dict[str, object] = orjson.loads(self.last.content)
        return body


@dataclass
class Sleeps:
    delays: list[float] = field(default_factory=list[float])

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def ok(payload: object, status: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, content=orjson.dumps(payload), headers=headers)


def collection(*items: object) -> dict[str, object]:
    return {"entity": "collection", "count": len(items), "items": list(items)}


def error_body(code: str = "BAD_REQUEST_ERROR", description: str = "boom", field_name: str | None = None) -> object:
    return {"error": {"code": code, "description": description, "source": "business", "field": field_name}}


def build(*responses: httpx.Response | Exception) -> tuple[RazorpayClient, Script, Sleeps]:
    script = Script(list(responses))
    sleeps = Sleeps()
    http = SafeHttpClient(OutboundHttpSettings(), resolver=public_dns, transport=httpx.MockTransport(script))
    return RazorpayClient(http, CREDENTIALS, base_url=BASE_URL, sleep=sleeps), script, sleeps


async def test_create_order_posts_json_with_basic_auth_and_parses_paise() -> None:
    client, script, _ = build(ok(ORDER))

    order = await client.create_order(amount=49900, currency="INR", receipt="rcpt_1", notes={"orderId": "o-1"})

    assert script.last.method == "POST"
    assert script.last.url.path == "/v1/orders"
    assert script.last.headers["authorization"] == EXPECTED_AUTHORIZATION
    assert script.last.headers["content-type"] == "application/json"
    assert script.last.headers["host"] == "api.razorpay.com"
    assert script.last_body == {"amount": 49900, "currency": "INR", "receipt": "rcpt_1", "notes": {"orderId": "o-1"}}
    assert (order.id, order.amount, order.amount_due, order.notes) == ("order_Abc123", 49900, 49900, {})
    assert order.created_at_utc == datetime.fromtimestamp(CREATED_AT, UTC)


async def test_fetch_order_and_order_payments_use_get() -> None:
    client, script, _ = build(ok(ORDER), ok(collection(PAYMENT)))

    order = await client.fetch_order("order_Abc123")
    payments = await client.order_payments("order_Abc123")

    assert [(request.method, request.url.path) for request in script.requests] == [
        ("GET", "/v1/orders/order_Abc123"),
        ("GET", "/v1/orders/order_Abc123/payments"),
    ]
    assert script.requests[0].content == b""
    assert order.status == "created"
    assert [payment.id for payment in payments] == ["pay_Abc123"]
    assert payments[0].is_captured
    assert payments[0].notes == {"orderId": "o-1"}


async def test_find_order_by_receipt_filters_and_prefers_the_latest_match() -> None:
    newer = {**ORDER, "id": "order_Newer1", "created_at": CREATED_AT + 10}
    other = {**ORDER, "id": "order_Other1", "receipt": "different", "created_at": CREATED_AT + 20}
    client, script, _ = build(ok(collection(ORDER, newer, other)), ok(collection()))

    found = await client.find_order_by_receipt("rcpt_1")
    missing = await client.find_order_by_receipt("rcpt_2")

    assert dict(script.requests[0].url.params) == {"receipt": "rcpt_1", "count": "10"}
    assert script.requests[0].url.path == "/v1/orders"
    assert found is not None
    assert found.id == "order_Newer1"
    assert missing is None


async def test_payments_listing_sends_epoch_window_and_paging() -> None:
    client, script, _ = build(ok(collection(PAYMENT)), ok(PAYMENT))

    listed = await client.list_payments(
        from_ts=datetime(2026, 10, 1, tzinfo=UTC), to_ts=datetime(2026, 10, 2, tzinfo=UTC), count=50, skip=100
    )
    fetched = await client.fetch_payment("pay_Abc123")

    assert dict(script.requests[0].url.params) == {
        "from": "1790812800",
        "to": "1790899200",
        "count": "50",
        "skip": "100",
    }
    assert script.requests[1].url.path == "/v1/payments/pay_Abc123"
    assert listed[0].amount == 49900
    assert fetched.fee == 1180


async def test_create_customer_asks_razorpay_to_return_the_existing_customer() -> None:
    customer = {"id": "cust_Abc123", "name": "Asha", "email": "asha@example.com", "contact": None, "created_at": 1}
    client, script, _ = build(ok(customer))

    created = await client.create_customer(name="Asha", email="asha@example.com", notes={"userId": "u-1"})

    assert script.last.url.path == "/v1/customers"
    assert script.last_body == {
        "name": "Asha",
        "email": "asha@example.com",
        "fail_existing": "0",
        "notes": {"userId": "u-1"},
    }
    assert created.id == "cust_Abc123"


async def test_create_plan_nests_the_item() -> None:
    plan = {
        "id": "plan_Abc123",
        "period": "monthly",
        "interval": 1,
        "item": {"id": "item_1", "name": "Pro", "amount": 99900, "currency": "INR"},
        "created_at": 1,
    }
    client, script, _ = build(ok(plan))

    created = await client.create_plan(
        PlanParams(period=PlanPeriod.MONTHLY, interval=1, name="Pro", amount=99900, currency="INR", description="d")
    )

    assert script.last_body == {
        "period": "monthly",
        "interval": 1,
        "item": {"name": "Pro", "amount": 99900, "currency": "INR", "description": "d"},
        "notes": {},
    }
    assert (created.amount, created.currency) == (99900, "INR")


async def test_subscription_lifecycle_calls_and_timestamp_helpers() -> None:
    scheduled = {**SUBSCRIPTION, "has_scheduled_changes": True, "change_scheduled_at": CREATED_AT + 5}
    client, script, _ = build(ok(SUBSCRIPTION), ok(SUBSCRIPTION), ok(SUBSCRIPTION), ok(scheduled))

    created = await client.create_subscription(plan_id="plan_Abc123", total_count=12, notes={"k": "v"})
    fetched = await client.fetch_subscription("sub_Abc123")
    cancelled = await client.cancel_subscription("sub_Abc123", at_cycle_end=True)
    updated = await client.update_subscription("sub_Abc123", plan_id="plan_New123")

    assert script.requests[0].url.path == "/v1/subscriptions"
    assert script.requests[0].method == "POST"
    assert orjson.loads(script.requests[0].content) == {
        "plan_id": "plan_Abc123",
        "total_count": 12,
        "customer_notify": 1,
        "notes": {"k": "v"},
    }
    assert script.requests[1].method == "GET"
    assert (script.requests[2].method, script.requests[2].url.path) == ("POST", "/v1/subscriptions/sub_Abc123/cancel")
    assert orjson.loads(script.requests[2].content) == {"cancel_at_cycle_end": 1}
    assert (script.requests[3].method, script.requests[3].url.path) == ("PATCH", "/v1/subscriptions/sub_Abc123")
    assert orjson.loads(script.requests[3].content) == {"plan_id": "plan_New123", "schedule_change_at": "cycle_end"}
    assert created.remaining_count == 11
    assert fetched.current_end_utc == datetime.fromtimestamp(CREATED_AT + 2_592_000, UTC)
    assert fetched.ended_at_utc is None
    assert cancelled.paid_count == 1
    assert updated.has_scheduled_changes
    assert updated.change_scheduled_at_utc == datetime.fromtimestamp(CREATED_AT + 5, UTC)


async def test_subscriptions_listing_sends_filters_window_and_paging() -> None:
    client, script, _ = build(ok(collection(SUBSCRIPTION)), ok(collection()))

    listed = await client.list_subscriptions(
        plan_id="plan_Abc123",
        from_ts=datetime(2026, 10, 1, tzinfo=UTC),
        to_ts=datetime(2026, 10, 2, tzinfo=UTC),
        count=20,
        skip=40,
    )
    bare = await client.list_subscriptions()

    assert script.requests[0].url.path == "/v1/subscriptions"
    assert dict(script.requests[0].url.params) == {
        "plan_id": "plan_Abc123",
        "from": "1790812800",
        "to": "1790899200",
        "count": "20",
        "skip": "40",
    }
    assert dict(script.requests[1].url.params) == {"count": "100", "skip": "0"}
    assert [item.id for item in listed] == ["sub_Abc123"]
    assert bare == []


async def test_subscriptions_listing_validates_the_plan_identifier() -> None:
    client, script, _ = build()

    with pytest.raises(RazorpayInvalidIdentifierError):
        await client.list_subscriptions(plan_id="plan/../x")

    assert script.requests == []


async def test_immediate_cancellation_and_plan_change_now() -> None:
    client, script, _ = build(ok(SUBSCRIPTION), ok(SUBSCRIPTION))

    await client.cancel_subscription("sub_Abc123", at_cycle_end=False)
    await client.update_subscription("sub_Abc123", plan_id="plan_New123", schedule_change_at=ScheduleChangeAt.NOW)

    assert orjson.loads(script.requests[0].content) == {"cancel_at_cycle_end": 0}
    assert orjson.loads(script.requests[1].content)["schedule_change_at"] == "now"


async def test_refund_calls() -> None:
    client, script, _ = build(ok(REFUND), ok(REFUND), ok(collection(REFUND)))

    created = await client.create_refund("pay_Abc123", amount=1000, notes={"refundId": "r-1"}, receipt="r-1")
    fetched = await client.fetch_refund("rfnd_Abc123")
    listed = await client.list_payment_refunds("pay_Abc123")

    assert (script.requests[0].method, script.requests[0].url.path) == ("POST", "/v1/payments/pay_Abc123/refund")
    assert orjson.loads(script.requests[0].content) == {"amount": 1000, "notes": {"refundId": "r-1"}, "receipt": "r-1"}
    assert script.requests[1].url.path == "/v1/refunds/rfnd_Abc123"
    assert script.requests[2].url.path == "/v1/payments/pay_Abc123/refunds"
    assert created.notes == {"refundId": "r-1"}
    assert (fetched.amount, fetched.status) == (1000, "pending")
    assert [refund.id for refund in listed] == ["rfnd_Abc123"]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, RazorpayAuthenticationError),
        (400, RazorpayBadRequestError),
        (404, RazorpayNotFoundError),
        (429, RazorpayRateLimitedError),
        (500, RazorpayServerError),
        (503, RazorpayServerError),
        (403, RazorpayUnexpectedStatusError),
        (302, RazorpayUnexpectedStatusError),
    ],
)
async def test_statuses_map_to_typed_errors(status: int, expected: type[RazorpayError]) -> None:
    client, _, _ = build(ok(error_body(), status))

    with pytest.raises(expected):
        await client.create_order(amount=100, currency="INR", receipt="r")


async def test_bad_request_carries_code_description_and_field() -> None:
    client, _, _ = build(ok(error_body("BAD_REQUEST_ERROR", "Order amount less than minimum", "amount"), 400))

    with pytest.raises(RazorpayBadRequestError) as caught:
        await client.create_order(amount=1, currency="INR", receipt="r")

    assert caught.value.status_code == 400
    assert caught.value.code == "BAD_REQUEST_ERROR"
    assert caught.value.description == "Order amount less than minimum"
    assert caught.value.field == "amount"
    assert "Order amount less than minimum" in str(caught.value)


async def test_error_with_unreadable_body_still_maps_by_status() -> None:
    client, _, _ = build(httpx.Response(502, content=b"<html>bad gateway</html>"))

    with pytest.raises(RazorpayServerError) as caught:
        await client.create_order(amount=100, currency="INR", receipt="r")

    assert caught.value.code is None
    assert str(caught.value) == "Razorpay responded with 502"


async def test_get_retries_server_errors_with_exponential_backoff() -> None:
    client, script, sleeps = build(ok(error_body(), 500), ok(error_body(), 502), ok(ORDER))

    order = await client.fetch_order("order_Abc123")

    assert order.id == "order_Abc123"
    assert len(script.requests) == 3
    assert sleeps.delays == [0.25, 0.5]


async def test_get_gives_up_after_three_attempts() -> None:
    client, script, sleeps = build(*[ok(error_body(), 503) for _ in range(5)])

    with pytest.raises(RazorpayServerError):
        await client.fetch_order("order_Abc123")

    assert len(script.requests) == 3
    assert len(sleeps.delays) == 2


async def test_get_retries_timeouts_and_connection_resets() -> None:
    client, script, sleeps = build(httpx.ReadTimeout("slow"), httpx.ReadError("reset"), ok(ORDER))

    await client.fetch_order("order_Abc123")

    assert len(script.requests) == 3
    assert len(sleeps.delays) == 2


async def test_get_honours_retry_after_within_the_cap() -> None:
    client, _, sleeps = build(
        ok(error_body(), 429, {"Retry-After": "1"}),
        ok(error_body(), 429, {"Retry-After": "120"}),
        ok(ORDER),
    )

    await client.fetch_order("order_Abc123")

    assert sleeps.delays == [1.0, RetryPolicy().retry_after_cap_seconds]


async def test_get_ignores_unparseable_retry_after() -> None:
    client, _, sleeps = build(ok(error_body(), 429, {"Retry-After": "soon"}), ok(ORDER))

    await client.fetch_order("order_Abc123")

    assert sleeps.delays == [0.25]


@pytest.mark.parametrize("status", [400, 401, 404])
async def test_get_never_retries_client_errors(status: int) -> None:
    client, script, sleeps = build(ok(error_body(), status), ok(ORDER))

    with pytest.raises(RazorpayError):
        await client.fetch_order("order_Abc123")

    assert len(script.requests) == 1
    assert sleeps.delays == []


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ReadTimeout("slow"),
        httpx.ConnectTimeout("slow"),
        httpx.ReadError("reset"),
        httpx.RemoteProtocolError("eof"),
    ],
)
async def test_post_timeout_is_ambiguous_and_never_retried(failure: Exception) -> None:
    client, script, sleeps = build(failure, ok(ORDER))

    with pytest.raises(RazorpayTimeoutError) as caught:
        await client.create_order(amount=100, currency="INR", receipt="r")

    assert caught.value.ambiguous
    assert len(script.requests) == 1
    assert sleeps.delays == []


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_post_and_patch_are_never_retried_on_errors(status: int) -> None:
    client, script, sleeps = build(ok(error_body(), status), ok(SUBSCRIPTION))

    with pytest.raises(RazorpayError):
        await client.create_subscription(plan_id="plan_Abc123", total_count=1)

    assert len(script.requests) == 1
    assert sleeps.delays == []


async def test_patch_timeout_is_not_retried() -> None:
    client, script, _ = build(httpx.ReadTimeout("slow"), ok(SUBSCRIPTION))

    with pytest.raises(RazorpayTimeoutError):
        await client.update_subscription("sub_Abc123", plan_id="plan_New123")

    assert len(script.requests) == 1


async def test_server_errors_are_flagged_ambiguous_and_client_errors_are_not() -> None:
    client, _, _ = build(ok(error_body(), 500), ok(error_body(), 400))

    with pytest.raises(RazorpayServerError) as server:
        await client.create_order(amount=100, currency="INR", receipt="r")
    with pytest.raises(RazorpayBadRequestError) as bad:
        await client.create_order(amount=100, currency="INR", receipt="r")

    assert server.value.ambiguous
    assert not bad.value.ambiguous


@pytest.mark.parametrize("identifier", ["", "../orders", "order/1", "order 1", "order?x=1", "a" * 65, "ord%2e"])
async def test_identifiers_are_validated_before_any_request(identifier: str) -> None:
    client, script, _ = build(ok(ORDER))

    with pytest.raises(RazorpayInvalidIdentifierError):
        await client.fetch_order(identifier)

    assert script.requests == []


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not json"),
        ok([ORDER]),
        ok({**ORDER, "amount": 499.5}),
        ok({**ORDER, "amount": "49900"}),
        ok({"id": "order_x"}),
    ],
)
async def test_unusable_success_bodies_raise_response_errors(response: httpx.Response) -> None:
    client, _, _ = build(response)

    with pytest.raises(RazorpayResponseError) as caught:
        await client.fetch_order("order_Abc123")

    assert "49900" not in str(caught.value)


async def test_list_without_items_is_a_response_error() -> None:
    client, _, _ = build(ok({"entity": "collection"}))

    with pytest.raises(RazorpayResponseError):
        await client.order_payments("order_Abc123")


async def test_secrets_never_reach_logs_errors_or_repr() -> None:
    client, _, _ = build(ok(error_body("SERVER_ERROR", "boom"), 500), httpx.ReadTimeout("slow"))

    with capture_logs() as logs:
        with pytest.raises(RazorpayServerError) as server:
            await client.create_order(amount=100, currency="INR", receipt="r")
        with pytest.raises(RazorpayTimeoutError) as timeout:
            await client.create_order(amount=100, currency="INR", receipt="r")

    rendered = repr(logs) + str(server.value) + str(timeout.value) + repr(client) + repr(CREDENTIALS)
    assert logs
    for secret in (
        KEY_SECRET,
        EXPECTED_AUTHORIZATION,
        "webhook-secret-value",
        base64.b64encode(KEY_SECRET.encode()).decode(),
    ):
        assert secret not in rendered


async def test_blocked_hosts_are_refused_by_the_safe_client() -> None:
    script = Script([ok(ORDER)])
    http = SafeHttpClient(
        OutboundHttpSettings(),
        resolver=public_dns,
        allowed_hosts=("api.razorpay.com",),
        transport=httpx.MockTransport(script),
    )
    client = RazorpayClient(http, CREDENTIALS, base_url="https://evil.example")

    with pytest.raises(OutboundRequestBlockedError, match="not allowed"):
        await client.fetch_order("order_Abc123")

    assert script.requests == []
