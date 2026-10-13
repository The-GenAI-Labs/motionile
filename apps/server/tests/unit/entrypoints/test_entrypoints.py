from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from procrastinate import App

from motionile.core.config import AppEnv, ProvidersMode, Settings
from motionile.entrypoints import api, mcp, worker

PRODUCTION_SETTINGS = Settings(
    app_env=AppEnv.PRODUCTION,
    providers_mode=ProvidersMode.LIVE,
    database_url="postgresql://app@db.internal/motionile",
    redis_url="redis://redis.internal:6379/0",
    allowed_origins=("https://motionile.com",),
)


@pytest.fixture
async def mcp_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=mcp.create_app()), base_url="http://test") as http:
        yield http


async def test_mcp_exposes_health_routes(mcp_client: AsyncClient) -> None:
    response = await mcp_client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_mcp_does_not_publish_api_docs(mcp_client: AsyncClient) -> None:
    assert (await mcp_client.get("/openapi.json")).status_code == 404


def test_module_level_apps_exist() -> None:
    assert api.app.title == "Motionile API"
    assert mcp.app.title == "Motionile MCP"
    assert isinstance(worker.app, App)


async def test_api_hides_docs_in_production() -> None:
    app = api.create_app(PRODUCTION_SETTINGS)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        assert (await http.get("/docs")).status_code == 404
        assert (await http.get("/openapi.json")).status_code == 404


async def test_api_allows_configured_origins() -> None:
    app = api.create_app(PRODUCTION_SETTINGS)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        allowed = await http.get("/health/live", headers={"Origin": "https://motionile.com"})
        rejected = await http.get("/health/live", headers={"Origin": "https://evil.example"})

    assert allowed.headers["access-control-allow-origin"] == "https://motionile.com"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert "access-control-allow-origin" not in rejected.headers
