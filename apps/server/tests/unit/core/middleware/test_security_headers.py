from collections.abc import AsyncIterator, Callable

import pytest
from fastapi import FastAPI, Response
from httpx import ASGITransport, AsyncClient
from starlette.types import Receive, Scope, Send

from motionile.core.middleware.security_headers import SECURITY_HEADERS, SecurityHeadersMiddleware
from motionile.entrypoints import api, mcp


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/plain")
    async def plain() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/framed")
    async def framed() -> Response:
        return Response(headers={"X-Frame-Options": "SAMEORIGIN"})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def test_adds_security_headers(client: AsyncClient) -> None:
    response = await client.get("/plain")

    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value


async def test_keeps_headers_set_by_the_route(client: AsyncClient) -> None:
    response = await client.get("/framed")

    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


async def test_adds_headers_to_not_found_responses(client: AsyncClient) -> None:
    response = await client.get("/missing")

    assert response.status_code == 404
    assert response.headers["X-Content-Type-Options"] == "nosniff"


async def test_passes_through_non_http_scopes() -> None:
    received: list[str] = []

    async def inner(scope: Scope, _receive: Receive, _send: Send) -> None:
        received.append(scope["type"])

    async def receive() -> dict[str, str]:
        return {"type": "lifespan.startup"}

    async def send(_message: object) -> None:
        return None

    await SecurityHeadersMiddleware(inner)({"type": "lifespan"}, receive, send)

    assert received == ["lifespan"]


@pytest.mark.parametrize("factory", [api.create_app, mcp.create_app])
async def test_entrypoints_send_security_headers(factory: Callable[[], FastAPI]) -> None:
    async with AsyncClient(transport=ASGITransport(app=factory()), base_url="http://test") as http:
        response = await http.get("/health/live")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
