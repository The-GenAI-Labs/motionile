from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from tests.fakes.probes import FakeProbe
from tests.fakes.resources import make_resources
from tests.fakes.settings import deployed_settings, make_settings

from motionile.core.config import AppEnv, Settings
from motionile.core.errors import PROBLEM_MEDIA_TYPE
from motionile.core.middleware.request_id import REQUEST_ID_HEADER
from motionile.entrypoints import api, mcp


def build_api(settings: Settings | None = None) -> tuple[FastAPI, FakeProbe, FakeProbe]:
    resolved = settings or make_settings()
    resources = make_resources(resolved)
    postgres = FakeProbe()
    redis = FakeProbe()
    application = api.create_app(resolved, resources=resources)
    pytest.MonkeyPatch().setattr(resources.database, "ping", postgres.ping)
    pytest.MonkeyPatch().setattr(resources.redis_store, "ping", redis.ping)
    return application, postgres, redis


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    application, _, _ = build_api()
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as http:
        yield http


async def get(application: FastAPI, path: str) -> httpx.Response:
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as http:
        return await http.get(path)


async def test_liveness_is_ok_with_request_id_and_security_headers(client: AsyncClient) -> None:
    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers[REQUEST_ID_HEADER]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"


async def test_readiness_reports_each_dependency() -> None:
    application, postgres, redis = build_api()

    response = await get(application, "/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"postgres": "ok", "redis": "ok"}}
    assert postgres.calls == 1
    assert redis.calls == 1


@pytest.mark.parametrize(
    ("failing", "expected"),
    [("postgres", {"postgres": "unavailable", "redis": "ok"}), ("redis", {"postgres": "ok", "redis": "unavailable"})],
)
async def test_readiness_returns_503_when_a_dependency_is_down(failing: str, expected: dict[str, str]) -> None:
    application, postgres, redis = build_api()
    (postgres if failing == "postgres" else redis).failure = ConnectionError("down")

    response = await get(application, "/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "checks": expected}


async def test_readiness_treats_timeouts_as_unavailable() -> None:
    application, postgres, _ = build_api()
    postgres.failure = TimeoutError()

    response = await get(application, "/health/ready")

    assert response.json()["checks"]["postgres"] == "unavailable"


async def test_unknown_routes_return_problem_details(client: AsyncClient) -> None:
    response = await client.get("/v1/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    body = response.json()
    assert body["code"] == "not_found"
    assert body["type"] == "urn:motionile:problem:not_found"
    assert body["requestId"] == response.headers[REQUEST_ID_HEADER]


@pytest.mark.parametrize("env", [AppEnv.LOCAL, AppEnv.CI])
async def test_test_support_routes_are_mounted_in_local_and_ci(env: AppEnv) -> None:
    application, _, _ = build_api(make_settings(env))

    assert "/v1/_test/echo" in application.openapi()["paths"]


@pytest.mark.parametrize("env", [AppEnv.STAGING, AppEnv.PRODUCTION])
async def test_test_support_routes_are_never_mounted_when_deployed(env: AppEnv) -> None:
    application, _, _ = build_api(deployed_settings(env))

    assert (await get(application, "/v1/_test/echo")).status_code == 404
    assert not any(path.startswith("/v1/_test") for path in application.openapi()["paths"])


async def test_test_support_routes_can_be_excluded_explicitly() -> None:
    settings = make_settings()
    application = api.create_app(settings, resources=make_resources(settings), include_test_routes=False)

    assert "/v1/_test/echo" not in application.openapi()["paths"]


async def test_test_support_routes_cannot_be_forced_on_when_deployed() -> None:
    settings = deployed_settings()
    application = api.create_app(settings, resources=make_resources(settings), include_test_routes=True)

    assert "/v1/_test/echo" not in application.openapi()["paths"]


async def test_production_hides_docs() -> None:
    application, _, _ = build_api(deployed_settings())

    assert (await get(application, "/docs")).status_code == 404
    assert (await get(application, "/openapi.json")).status_code == 404


async def test_production_sends_hsts() -> None:
    application, _, _ = build_api(deployed_settings())

    response = await get(application, "/health/live")

    assert response.headers["strict-transport-security"].startswith("max-age=")


async def test_operation_ids_follow_tag_and_function_name() -> None:
    application, _, _ = build_api()

    operation_ids = {
        operation["operationId"] for path in application.openapi()["paths"].values() for operation in path.values()
    }

    assert {"health_live", "health_ready", "test_support_echo"} <= operation_ids


async def test_error_responses_are_documented_as_problem_json() -> None:
    application, _, _ = build_api()

    responses = application.openapi()["paths"]["/v1/_test/echo"]["post"]["responses"]

    assert set(responses["422"]["content"]) == {PROBLEM_MEDIA_TYPE}
    assert set(responses["429"]["content"]) == {PROBLEM_MEDIA_TYPE}
    assert set(responses["200"]["content"]) == {"application/json"}


async def test_mcp_app_only_exposes_health_and_hides_docs() -> None:
    settings = make_settings()
    application = mcp.create_app(settings, resources=make_resources(settings))

    assert (await get(application, "/health/live")).status_code == 200
    assert (await get(application, "/docs")).status_code == 404
    assert (await get(application, "/v1/_test/echo")).status_code == 404
