import asyncio
from collections.abc import AsyncIterator
from typing import cast
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from motionile.core.config import RedisSettings, Settings
from motionile.core.errors import PROBLEM_MEDIA_TYPE
from motionile.core.idempotency import REPLAYED_HEADER
from motionile.core.middleware.request_id import REQUEST_ID_HEADER
from motionile.core.resources import Resources, build_resources
from motionile.entrypoints.api import create_app
from motionile.modules.audit import AuditLogEntry

ALLOWED_ORIGIN = "http://localhost:3000"
CONCURRENT_REQUESTS = 10


@pytest.fixture
async def client(settings: Settings, resources: Resources) -> AsyncIterator[AsyncClient]:
    application = create_app(settings, resources=resources)
    async with AsyncClient(
        transport=ASGITransport(app=application, client=("203.0.113.50", 5000)), base_url="http://test"
    ) as http:
        yield http


async def audit_rows_for(resources: Resources, item_id: str) -> int:
    async with resources.database.session() as session:
        statement = select(func.count()).select_from(AuditLogEntry).where(AuditLogEntry.target_id == item_id)
        return (await session.execute(statement)).scalar_one()


def assert_problem(response: httpx.Response, status: int, code: str) -> dict[str, object]:
    assert response.status_code == status
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    body: dict[str, object] = response.json()
    assert body["status"] == status
    assert body["code"] == code
    assert body["type"] == f"urn:motionile:problem:{code}"
    assert body["requestId"] == response.headers[REQUEST_ID_HEADER]
    assert isinstance(body["title"], str)
    return body


async def test_echo_passes_every_middleware(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/_test/echo",
        json={"message": "  hi  ", "repeatCount": 2},
        headers={"Origin": ALLOWED_ORIGIN, REQUEST_ID_HEADER: "client-request-0001"},
    )

    assert response.status_code == 200
    assert response.json() == {"message": "hi", "repeatCount": 2, "requestId": "client-request-0001"}
    assert response.headers[REQUEST_ID_HEADER] == "client-request-0001"
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert "server" not in response.headers
    assert int(response.headers["ratelimit-remaining"]) >= 0


async def test_invalid_request_ids_are_replaced(client: AsyncClient) -> None:
    response = await client.get("/health/live", headers={REQUEST_ID_HEADER: "bad id\r\n"})

    assert response.headers[REQUEST_ID_HEADER] != "bad id"
    assert len(response.headers[REQUEST_ID_HEADER]) == 32


async def test_preflight_allows_only_configured_origins(client: AsyncClient) -> None:
    preflight = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}

    allowed = await client.options("/v1/_test/echo", headers={"Origin": ALLOWED_ORIGIN, **preflight})
    denied = await client.options("/v1/_test/echo", headers={"Origin": "https://evil.example", **preflight})

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert "access-control-allow-origin" not in denied.headers


@pytest.mark.parametrize(
    "headers",
    [{"Origin": "https://evil.example"}, {"Origin": "null"}, {"Referer": "https://evil.example/page"}],
)
async def test_origin_guard_blocks_foreign_state_changes(client: AsyncClient, headers: dict[str, str]) -> None:
    response = await client.post("/v1/_test/echo", json={"message": "hi"}, headers=headers)

    assert_problem(response, 403, "origin_not_allowed")
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_validation_errors_use_camel_case_fields(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/_test/echo", json={"message": "", "repeatCount": 99, "extra": True}, headers={"Origin": ALLOWED_ORIGIN}
    )

    assert_problem(response, 422, "validation_failed")
    errors = cast("list[dict[str, str]]", response.json()["errors"])
    fields = {error["field"] for error in errors}
    assert fields == {"body.message", "body.repeatCount", "body.extra"}


async def test_malformed_json_is_a_problem(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/_test/echo",
        content=b"{not json",
        headers={"Origin": ALLOWED_ORIGIN, "Content-Type": "application/json"},
    )

    assert_problem(response, 422, "validation_failed")


async def test_method_not_allowed_is_a_problem(client: AsyncClient) -> None:
    response = await client.get("/v1/_test/echo")

    assert_problem(response, 405, "method_not_allowed")


async def test_rate_limit_returns_429_with_headers(client: AsyncClient) -> None:
    responses = [await client.get("/v1/_test/rate-limited") for _ in range(4)]

    assert [response.status_code for response in responses[:3]] == [200, 200, 200]
    assert [response.headers["ratelimit-remaining"] for response in responses[:3]] == ["2", "1", "0"]
    limited = responses[3]
    assert_problem(limited, 429, "rate_limited")
    assert limited.headers["ratelimit-limit"] == "3"
    assert 1 <= int(limited.headers["retry-after"]) <= 10


async def test_idempotent_create_replays_and_audits_once(client: AsyncClient, resources: Resources) -> None:
    headers = {"Origin": ALLOWED_ORIGIN, "Idempotency-Key": "create-item-0001"}

    first = await client.post("/v1/_test/idempotent", json={"itemName": "widget"}, headers=headers)
    second = await client.post("/v1/_test/idempotent", json={"itemName": "widget"}, headers=headers)
    reused = await client.post("/v1/_test/idempotent", json={"itemName": "other"}, headers=headers)
    missing = await client.post("/v1/_test/idempotent", json={"itemName": "x"}, headers={"Origin": ALLOWED_ORIGIN})

    assert first.status_code == 201
    assert REPLAYED_HEADER not in first.headers
    assert second.status_code == 201
    assert second.headers[REPLAYED_HEADER] == "true"
    assert second.json() == first.json()
    assert second.headers["location"] == first.headers["location"]
    assert_problem(reused, 409, "idempotency_key_reused")
    assert_problem(missing, 400, "idempotency_key_required")
    assert await audit_rows_for(resources, first.json()["id"]) == 1


async def test_concurrent_idempotent_requests_create_one_item(client: AsyncClient, resources: Resources) -> None:
    headers = {"Origin": ALLOWED_ORIGIN, "Idempotency-Key": "create-item-concurrent"}

    responses = await asyncio.gather(
        *(
            client.post("/v1/_test/idempotent", json={"itemName": "widget"}, headers=headers)
            for _ in range(CONCURRENT_REQUESTS)
        )
    )

    created = [response for response in responses if response.status_code == 201]
    originals = [response for response in created if REPLAYED_HEADER not in response.headers]
    conflicts = [response for response in responses if response.status_code == 409]
    assert len(originals) == 1
    assert len(created) + len(conflicts) == CONCURRENT_REQUESTS
    assert all(response.json()["code"] == "idempotency_request_in_progress" for response in conflicts)
    assert {response.json()["id"] for response in created} == {originals[0].json()["id"]}
    item_id = str(UUID(originals[0].json()["id"]))
    assert await audit_rows_for(resources, item_id) == 1


async def test_readiness_with_real_dependencies(client: AsyncClient) -> None:
    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"postgres": "ok", "redis": "ok"}}


async def test_readiness_reports_unreachable_redis(settings: Settings) -> None:
    broken = settings.model_copy(
        update={"redis": RedisSettings(url="redis://127.0.0.1:1/0", socket_timeout_seconds=0.5)}
    )
    resources = build_resources(broken, application_name="motionile-integration")
    application: FastAPI = create_app(broken, resources=resources)

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as http:
        response = await http.get("/health/ready")
    await resources.aclose()

    assert response.status_code == 503
    assert response.json()["checks"] == {"postgres": "ok", "redis": "unavailable"}


async def test_default_policy_fails_open_when_redis_is_down(settings: Settings) -> None:
    broken = settings.model_copy(
        update={"redis": RedisSettings(url="redis://127.0.0.1:1/0", socket_timeout_seconds=0.5)}
    )
    resources = build_resources(broken, application_name="motionile-integration")
    application = create_app(broken, resources=resources)

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as http:
        response = await http.post("/v1/_test/echo", json={"message": "hi"})
    await resources.aclose()

    assert response.status_code == 200
