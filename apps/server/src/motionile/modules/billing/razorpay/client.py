import asyncio
import base64
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from typing import Any, cast
from urllib.parse import urlencode

import httpx
import orjson
import structlog
from pydantic import ValidationError

from motionile.core.http.safe_client import ResponseTooLargeError, SafeHttpClient, SafeResponse
from motionile.modules.billing.razorpay.api import PlanParams, ScheduleChangeAt
from motionile.modules.billing.razorpay.credentials import RazorpayCredentials
from motionile.modules.billing.razorpay.exceptions import (
    RazorpayApiError,
    RazorpayAuthenticationError,
    RazorpayBadRequestError,
    RazorpayError,
    RazorpayInvalidIdentifierError,
    RazorpayNotFoundError,
    RazorpayRateLimitedError,
    RazorpayResponseError,
    RazorpayServerError,
    RazorpayTimeoutError,
    RazorpayUnexpectedStatusError,
)
from motionile.modules.billing.razorpay.models import (
    RazorpayCustomer,
    RazorpayModel,
    RazorpayOrder,
    RazorpayPayment,
    RazorpayPlan,
    RazorpayRefund,
    RazorpaySubscription,
)

logger = structlog.get_logger(__name__)

IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9_]{1,64}")
SERVER_ERROR_FLOOR = 500
type Sleep = Callable[[float], Awaitable[None]]
type JsonObject = dict[str, Any]


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    base_delay_seconds: float = 0.25
    max_delay_seconds: float = 2.0
    retry_after_cap_seconds: float = 5.0

    def backoff(self, attempt: int) -> float:
        return min(self.base_delay_seconds * 2 ** (attempt - 1), self.max_delay_seconds)


def identifier(value: str) -> str:
    if IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise RazorpayInvalidIdentifierError
    return value


def basic_authorization(credentials: RazorpayCredentials) -> str:
    pair = f"{credentials.key_id}:{credentials.key_secret.get_secret_value()}"
    return "Basic " + base64.b64encode(pair.encode()).decode()


def retry_after_seconds(response: SafeResponse) -> float | None:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def error_fields(response: SafeResponse) -> tuple[str | None, str | None, str | None]:
    try:
        body: object = response.json()
    except ValueError:
        return None, None, None
    if not isinstance(body, dict):
        return None, None, None
    error = cast("Mapping[str, object]", body).get("error")
    if not isinstance(error, dict):
        return None, None, None
    fields = cast("Mapping[str, object]", error)

    def text(key: str) -> str | None:
        value = fields.get(key)
        return value if isinstance(value, str) else None

    return text("code"), text("description"), text("field")


def api_error_for(response: SafeResponse) -> RazorpayApiError:
    code, description, field = error_fields(response)
    status = response.status_code
    if status == HTTPStatus.UNAUTHORIZED:
        return RazorpayAuthenticationError(status, code=code, description=description, field=field)
    if status == HTTPStatus.BAD_REQUEST:
        return RazorpayBadRequestError(status, code=code, description=description, field=field)
    if status == HTTPStatus.NOT_FOUND:
        return RazorpayNotFoundError(status, code=code, description=description, field=field)
    if status == HTTPStatus.TOO_MANY_REQUESTS:
        return RazorpayRateLimitedError(
            status,
            code=code,
            description=description,
            field=field,
            retry_after_seconds=retry_after_seconds(response),
        )
    if status >= SERVER_ERROR_FLOOR:
        return RazorpayServerError(status, code=code, description=description, field=field)
    return RazorpayUnexpectedStatusError(status, code=code, description=description, field=field)


def is_retryable(error: RazorpayError) -> bool:
    return isinstance(error, RazorpayTimeoutError | RazorpayRateLimitedError | RazorpayServerError)


def without_none(values: Mapping[str, object]) -> JsonObject:
    return {key: value for key, value in values.items() if value is not None}


class RazorpayClient:
    def __init__(
        self,
        http: SafeHttpClient,
        credentials: RazorpayCredentials,
        *,
        base_url: str,
        sleep: Sleep = asyncio.sleep,
        retry: RetryPolicy | None = None,
    ) -> None:
        self._http = http
        self._authorization = basic_authorization(credentials)
        self._base_url = base_url.rstrip("/")
        self._sleep = sleep
        self._retry = retry or RetryPolicy()

    def __repr__(self) -> str:
        return f"RazorpayClient(base_url={self._base_url!r})"

    async def _send_once(self, method: str, url: str, content: bytes | None) -> SafeResponse:
        headers = {"Authorization": self._authorization, "Accept": "application/json"}
        if content is not None:
            headers["Content-Type"] = "application/json"
        try:
            return await self._http.request(method, url, headers=headers, content=content)
        except httpx.TransportError as error:
            raise RazorpayTimeoutError(type(error).__name__) from None
        except ResponseTooLargeError:
            raise RazorpayResponseError("the response was too large") from None

    async def _attempt(self, method: str, url: str, content: bytes | None) -> JsonObject:
        response = await self._send_once(method, url, content)
        if not HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES:
            raise api_error_for(response)
        try:
            payload: object = response.json()
        except ValueError:
            raise RazorpayResponseError("the body is not JSON") from None
        if not isinstance(payload, dict):
            raise RazorpayResponseError("the body is not a JSON object")
        return cast("JsonObject", payload)

    def _delay_for(self, error: RazorpayError, attempt: int) -> float:
        backoff = self._retry.backoff(attempt)
        if isinstance(error, RazorpayRateLimitedError) and error.retry_after_seconds is not None:
            return min(error.retry_after_seconds, self._retry.retry_after_cap_seconds)
        return backoff

    async def _request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str | int] | None = None,
        body: Mapping[str, object] | None = None,
    ) -> JsonObject:
        url = f"{self._base_url}{path}"
        if query:
            url = f"{url}?{urlencode(dict(query))}"
        content = orjson.dumps(dict(body)) if body is not None else None
        attempts = self._retry.attempts if method == "GET" else 1
        attempt = 1
        while True:
            try:
                return await self._attempt(method, url, content)
            except RazorpayError as error:
                log = logger.warning if is_retryable(error) else logger.info
                log("razorpay.request_failed", method=method, path=path, attempt=attempt, error=type(error).__name__)
                if attempt >= attempts or not is_retryable(error):
                    raise
                await self._sleep(self._delay_for(error, attempt))
                attempt += 1

    @staticmethod
    def _parse[ModelT: RazorpayModel](model: type[ModelT], payload: JsonObject) -> ModelT:
        try:
            return model.model_validate(payload)
        except ValidationError:
            raise RazorpayResponseError(f"the {model.__name__} payload has an unexpected shape") from None

    @staticmethod
    def _parse_items[ModelT: RazorpayModel](model: type[ModelT], payload: JsonObject) -> list[ModelT]:
        items = payload.get("items")
        if not isinstance(items, list):
            raise RazorpayResponseError(f"the {model.__name__} list has no items")
        return [
            RazorpayClient._parse(model, cast("JsonObject", item))
            for item in cast("list[object]", items)
            if isinstance(item, dict)
        ]

    async def create_order(
        self, *, amount: int, currency: str, receipt: str, notes: Mapping[str, str] | None = None
    ) -> RazorpayOrder:
        payload = await self._request(
            "POST",
            "/v1/orders",
            body={"amount": amount, "currency": currency, "receipt": receipt, "notes": dict(notes or {})},
        )
        return self._parse(RazorpayOrder, payload)

    async def fetch_order(self, order_id: str) -> RazorpayOrder:
        return self._parse(RazorpayOrder, await self._request("GET", f"/v1/orders/{identifier(order_id)}"))

    async def find_order_by_receipt(self, receipt: str) -> RazorpayOrder | None:
        payload = await self._request("GET", "/v1/orders", query={"receipt": receipt, "count": 10})
        matches = [order for order in self._parse_items(RazorpayOrder, payload) if order.receipt == receipt]
        return max(matches, key=lambda order: order.created_at, default=None)

    async def order_payments(self, order_id: str) -> list[RazorpayPayment]:
        payload = await self._request("GET", f"/v1/orders/{identifier(order_id)}/payments")
        return self._parse_items(RazorpayPayment, payload)

    async def fetch_payment(self, payment_id: str) -> RazorpayPayment:
        return self._parse(RazorpayPayment, await self._request("GET", f"/v1/payments/{identifier(payment_id)}"))

    async def list_payments(
        self, *, from_ts: datetime, to_ts: datetime, count: int = 100, skip: int = 0
    ) -> list[RazorpayPayment]:
        payload = await self._request(
            "GET",
            "/v1/payments",
            query={"from": int(from_ts.timestamp()), "to": int(to_ts.timestamp()), "count": count, "skip": skip},
        )
        return self._parse_items(RazorpayPayment, payload)

    async def create_customer(
        self, *, name: str, email: str | None = None, contact: str | None = None, notes: Mapping[str, str] | None = None
    ) -> RazorpayCustomer:
        payload = await self._request(
            "POST",
            "/v1/customers",
            body=without_none(
                {"name": name, "email": email, "contact": contact, "fail_existing": "0", "notes": dict(notes or {})}
            ),
        )
        return self._parse(RazorpayCustomer, payload)

    async def create_plan(self, plan: PlanParams) -> RazorpayPlan:
        item = without_none(
            {"name": plan.name, "amount": plan.amount, "currency": plan.currency, "description": plan.description}
        )
        payload = await self._request(
            "POST",
            "/v1/plans",
            body={
                "period": plan.period.value,
                "interval": plan.interval,
                "item": item,
                "notes": dict(plan.notes or {}),
            },
        )
        return self._parse(RazorpayPlan, payload)

    async def create_subscription(
        self,
        *,
        plan_id: str,
        total_count: int,
        notes: Mapping[str, str] | None = None,
        customer_notify: bool = True,
    ) -> RazorpaySubscription:
        payload = await self._request(
            "POST",
            "/v1/subscriptions",
            body={
                "plan_id": plan_id,
                "total_count": total_count,
                "customer_notify": 1 if customer_notify else 0,
                "notes": dict(notes or {}),
            },
        )
        return self._parse(RazorpaySubscription, payload)

    async def fetch_subscription(self, subscription_id: str) -> RazorpaySubscription:
        payload = await self._request("GET", f"/v1/subscriptions/{identifier(subscription_id)}")
        return self._parse(RazorpaySubscription, payload)

    async def list_subscriptions(
        self,
        *,
        plan_id: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        count: int = 100,
        skip: int = 0,
    ) -> list[RazorpaySubscription]:
        query: dict[str, str | int] = {"count": count, "skip": skip}
        if plan_id is not None:
            query["plan_id"] = identifier(plan_id)
        if from_ts is not None:
            query["from"] = int(from_ts.timestamp())
        if to_ts is not None:
            query["to"] = int(to_ts.timestamp())
        payload = await self._request("GET", "/v1/subscriptions", query=query)
        return self._parse_items(RazorpaySubscription, payload)

    async def cancel_subscription(self, subscription_id: str, *, at_cycle_end: bool) -> RazorpaySubscription:
        payload = await self._request(
            "POST",
            f"/v1/subscriptions/{identifier(subscription_id)}/cancel",
            body={"cancel_at_cycle_end": 1 if at_cycle_end else 0},
        )
        return self._parse(RazorpaySubscription, payload)

    async def update_subscription(
        self, subscription_id: str, *, plan_id: str, schedule_change_at: ScheduleChangeAt = ScheduleChangeAt.CYCLE_END
    ) -> RazorpaySubscription:
        payload = await self._request(
            "PATCH",
            f"/v1/subscriptions/{identifier(subscription_id)}",
            body={"plan_id": plan_id, "schedule_change_at": schedule_change_at.value},
        )
        return self._parse(RazorpaySubscription, payload)

    async def create_refund(
        self,
        payment_id: str,
        *,
        amount: int,
        notes: Mapping[str, str] | None = None,
        receipt: str | None = None,
    ) -> RazorpayRefund:
        payload = await self._request(
            "POST",
            f"/v1/payments/{identifier(payment_id)}/refund",
            body=without_none({"amount": amount, "notes": dict(notes or {}), "receipt": receipt}),
        )
        return self._parse(RazorpayRefund, payload)

    async def fetch_refund(self, refund_id: str) -> RazorpayRefund:
        return self._parse(RazorpayRefund, await self._request("GET", f"/v1/refunds/{identifier(refund_id)}"))

    async def list_payment_refunds(self, payment_id: str) -> list[RazorpayRefund]:
        payload = await self._request("GET", f"/v1/payments/{identifier(payment_id)}/refunds")
        return self._parse_items(RazorpayRefund, payload)
