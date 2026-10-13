from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from motionile.entrypoints.api import create_app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as http:
        yield http


@pytest.mark.parametrize("path", ["/health/live", "/health/ready"])
async def test_health_routes_report_ok(client: AsyncClient, path: str) -> None:
    response = await client.get(path)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_unknown_route_returns_not_found(client: AsyncClient) -> None:
    response = await client.get("/health/unknown")

    assert response.status_code == 404
