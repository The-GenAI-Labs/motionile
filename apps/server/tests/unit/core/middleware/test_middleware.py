import json
from collections.abc import AsyncIterator

import pytest
import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse
from httpx import ASGITransport, AsyncClient
from starlette.types import Message, Receive, Scope, Send

from motionile.core.errors import register_exception_handlers
from motionile.core.middleware.access_log import AccessLogMiddleware
from motionile.core.middleware.origin_guard import OriginGuardMiddleware, origin_of
from motionile.core.middleware.request_id import REQUEST_ID_HEADER, RequestIdMiddleware
from motionile.core.middleware.security_headers import SecurityHeadersMiddleware, security_headers
from motionile.core.middleware.unhandled_errors import UnhandledErrorMiddleware

ALLOWED = "https://motionile.com"


def build_app(*, require_origin: bool = False, hsts: int = 0) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/items/{item_id}")
    async def read_item(item_id: int, request: Request) -> dict[str, object]:
        return {"item": item_id, "requestId": request.state.request_id}

    @app.post("/items")
    async def create_item() -> dict[str, str]:
        return {"status": "created"}

    @app.post("/v1/webhooks/razorpay")
    async def webhook() -> dict[str, str]:
        return {"status": "received"}

    @app.get("/public")
    async def public() -> Response:
        return PlainTextResponse("cached", headers={"Cache-Control": "public, max-age=60", "Server": "uvicorn"})

    @app.get("/crash")
    async def crash() -> None:
        message = "secret internals"
        raise RuntimeError(message)

    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(
        OriginGuardMiddleware,
        allowed_origins=[ALLOWED],
        exempt_path_prefixes=["/v1/webhooks"],
        require_origin=require_origin,
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts_max_age_seconds=hsts)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RequestIdMiddleware)
    return app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=build_app()), base_url="http://test") as http:
        yield http


async def test_generates_request_id_when_missing(client: AsyncClient) -> None:
    response = await client.get("/items/1")

    request_id = response.headers[REQUEST_ID_HEADER]
    assert len(request_id) == 32
    assert response.json()["requestId"] == request_id


async def test_accepts_valid_incoming_request_id(client: AsyncClient) -> None:
    response = await client.get("/items/1", headers={REQUEST_ID_HEADER: "trace-abc_123.x"})

    assert response.headers[REQUEST_ID_HEADER] == "trace-abc_123.x"


@pytest.mark.parametrize("value", ["short", "has spaces in it", "x" * 65, "<script>alert</script>"])
async def test_replaces_invalid_incoming_request_id(client: AsyncClient, value: str) -> None:
    response = await client.get("/items/1", headers={REQUEST_ID_HEADER: value})

    assert response.headers[REQUEST_ID_HEADER] != value


async def test_sets_security_headers_and_no_store(client: AsyncClient) -> None:
    response = await client.get("/items/1")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "camera=()" in response.headers["permissions-policy"]
    assert response.headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in response.headers


async def test_keeps_explicit_cache_control_and_strips_server(client: AsyncClient) -> None:
    response = await client.get("/public")

    assert response.headers["cache-control"] == "public, max-age=60"
    assert "server" not in response.headers


async def test_sets_hsts_when_configured() -> None:
    async with AsyncClient(transport=ASGITransport(app=build_app(hsts=31536000)), base_url="http://test") as http:
        response = await http.get("/items/1")

    assert response.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"


def test_security_headers_without_hsts() -> None:
    assert "Strict-Transport-Security" not in security_headers(hsts_max_age_seconds=0)


async def test_origin_guard_allows_safe_methods_from_anywhere(client: AsyncClient) -> None:
    response = await client.get("/items/1", headers={"Origin": "https://evil.example"})

    assert response.status_code == 200


async def test_origin_guard_allows_listed_origin(client: AsyncClient) -> None:
    response = await client.post("/items", headers={"Origin": ALLOWED})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Origin": "https://motionile.com.evil.example"},
        {"Referer": "https://evil.example/page"},
    ],
)
async def test_origin_guard_rejects_other_origins(client: AsyncClient, headers: dict[str, str]) -> None:
    response = await client.post("/items", headers=headers)

    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "origin_not_allowed"
    assert body["requestId"] == response.headers[REQUEST_ID_HEADER]
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_origin_guard_uses_referer_as_fallback(client: AsyncClient) -> None:
    response = await client.post("/items", headers={"Referer": f"{ALLOWED}/create?x=1"})

    assert response.status_code == 200


async def test_origin_guard_skips_exempt_prefixes(client: AsyncClient) -> None:
    response = await client.post("/v1/webhooks/razorpay", headers={"Origin": "https://api.razorpay.com"})

    assert response.status_code == 200


async def test_origin_guard_allows_requests_without_origin_by_default(client: AsyncClient) -> None:
    assert (await client.post("/items")).status_code == 200


async def test_origin_guard_can_require_an_origin() -> None:
    async with AsyncClient(transport=ASGITransport(app=build_app(require_origin=True)), base_url="http://test") as http:
        response = await http.post("/items")

    assert response.status_code == 403


def test_origin_of_parses_urls() -> None:
    assert origin_of("https://Motionile.com:8443/a?b") == "https://motionile.com:8443"
    assert origin_of("not a url") is None


async def test_unhandled_errors_become_problems_with_headers(client: AsyncClient) -> None:
    response = await client.get("/crash")

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.json()["requestId"] == response.headers[REQUEST_ID_HEADER]
    assert "secret internals" not in response.text


async def test_unhandled_error_after_response_started_is_reraised() -> None:
    async def partial(_scope: Scope, _receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        message = "late failure"
        raise RuntimeError(message)

    sent: list[Message] = []

    async def record(message: Message) -> None:
        sent.append(message)

    async def receive() -> Message:
        return {"type": "http.request", "body": b""}

    middleware = UnhandledErrorMiddleware(partial)
    with pytest.raises(RuntimeError, match="late failure"):
        await middleware({"type": "http", "method": "GET", "path": "/", "headers": []}, receive, record)
    assert sent[0]["status"] == 200


async def test_access_log_records_route_status_and_latency(capfd: pytest.CaptureFixture[str]) -> None:
    structlog.configure(processors=[structlog.processors.JSONRenderer()])
    async with AsyncClient(transport=ASGITransport(app=build_app()), base_url="http://test") as http:
        await http.get("/items/7")

    lines = [json.loads(line) for line in capfd.readouterr().out.strip().splitlines() if line.startswith("{")]
    record = next(line for line in lines if line.get("event") == "http.request")
    assert record["route"] == "/items/{item_id}"
    assert record["status"] == 200
    assert record["method"] == "GET"
    assert record["duration_ms"] >= 0
    structlog.reset_defaults()


async def test_non_http_scopes_pass_through() -> None:
    seen: list[str] = []

    async def inner(scope: Scope, _receive: Receive, _send: Send) -> None:
        seen.append(scope["type"])

    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    async def send(_: Message) -> None:
        return None

    for middleware in (
        RequestIdMiddleware(inner),
        AccessLogMiddleware(inner),
        SecurityHeadersMiddleware(inner),
        OriginGuardMiddleware(inner, allowed_origins=[]),
        UnhandledErrorMiddleware(inner),
    ):
        await middleware({"type": "lifespan"}, receive, send)

    assert seen == ["lifespan"] * 5
