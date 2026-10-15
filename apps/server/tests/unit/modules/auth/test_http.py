import secrets
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from tests.fakes.auth import AuthState

from motionile.entrypoints.api import create_app
from motionile.modules.auth.events import UserRegistered
from motionile.modules.auth.service import AuthService


@pytest.fixture
async def client(auth_service: AuthService) -> AsyncIterator[AsyncClient]:
    app = create_app(auth_service.resources.settings, resources=auth_service.resources)
    app.state.auth_runtime = auth_service.runtime
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://localhost:8000",
        headers={"Origin": "http://localhost:3000", "X-Turnstile-Token": "test-pass"},
    ) as client:
        yield client


async def test_full_http_session_flow(client: AsyncClient, auth_state: AuthState) -> None:
    result = await client.post(
        "/v1/auth/register", json={"name": "API", "email": "api@example.com", "password": "api-test-passphrase"}
    )
    assert result.status_code == 202, result.text
    code = auth_state.notifications[-1].code
    verified = await client.post("/v1/auth/verify", json={"code": code})
    assert verified.status_code == 200, verified.text
    assert (await client.get("/v1/auth/me")).status_code == 200
    headers = {"X-CSRF-Token": client.cookies["mo_csrf"]}
    refreshed = await client.post("/v1/auth/refresh", headers=headers)
    assert refreshed.status_code == 204, refreshed.text
    assert refreshed.content == b""
    assert (await client.post("/v1/auth/logout")).status_code == 403
    logout = await client.post("/v1/auth/logout", headers={"X-CSRF-Token": client.cookies["mo_csrf"]})
    assert logout.status_code == 204
    assert (await client.get("/v1/auth/me")).status_code == 401


@pytest.mark.parametrize("path", ["/register", "/login", "/otp/request", "/password/forgot"])
async def test_turnstile_is_required(client: AsyncClient, path: str) -> None:
    body = (
        {"name": "API", "email": "api@example.com", "password": "api-test-passphrase"}
        if path == "/register"
        else {"identifier": "api@example.com", "password": "api-test-passphrase"}
        if path == "/login"
        else {"identifier": "api@example.com"}
    )
    missing = await client.post("/v1/auth" + path, headers={"X-Turnstile-Token": ""}, json=body)
    assert missing.status_code == 400
    assert missing.json()["code"] == "turnstile_required"
    invalid = await client.post("/v1/auth" + path, headers={"X-Turnstile-Token": "fail"}, json=body)
    assert invalid.status_code == 403
    assert invalid.json()["code"] == "turnstile_failed"


async def test_origin_required_and_jwks_cached(client: AsyncClient) -> None:
    blocked = await client.post(
        "/v1/auth/login", headers={"Origin": "null"}, json={"identifier": "api@example.com", "password": "anything"}
    )
    assert blocked.status_code == 403
    jwks = await client.get("/v1/auth/jwks.json")
    assert jwks.status_code == 200
    assert jwks.headers["cache-control"] == "public, max-age=300"
    assert "d" not in jwks.json()["keys"][0]


async def test_oauth_browser_binding_flow(client: AsyncClient, auth_service: AuthService) -> None:
    registered: list[UserRegistered] = []

    async def capture(event: UserRegistered) -> None:
        registered.append(event)

    auth_service.resources.events.subscribe(UserRegistered, capture, name="test.oauth.registration")
    start = await client.get("/v1/auth/oauth/google/start")
    assert start.status_code == 302, start.text
    provider = await client.get(start.headers["location"])
    assert provider.status_code == 302, provider.text
    callback = await client.get(provider.headers["location"])
    assert callback.headers["location"] == "http://localhost:3000/dashboard", callback.text
    user = await client.get("/v1/auth/me")
    assert user.status_code == 200
    assert user.json()["linkedProviders"] == ["google"]
    assert len(registered) == 1
    assert str(registered[0].user_id) == user.json()["id"]
    assert (await client.get(provider.headers["location"])).headers["location"].endswith("error=oauth_failed")


@pytest.mark.parametrize("body", [[], "invalid", 1])
async def test_non_object_requests_are_validation_errors(client: AsyncClient, body: object) -> None:
    response = await client.post("/v1/auth/login", json=body)
    assert response.status_code == 422


async def test_auth_logs_and_audits_exclude_secrets(
    client: AsyncClient, auth_state: AuthState, capfd: pytest.CaptureFixture[str]
) -> None:
    password = secrets.token_urlsafe(24)
    await client.post(
        "/v1/auth/register", json={"name": "Private", "email": "private@example.com", "password": password}
    )
    code = auth_state.notifications[-1].code
    assert code is not None
    confidential_values = [password, code, *client.cookies.values()]
    verified = await client.post("/v1/auth/verify", json={"code": code})
    confidential_values.extend(client.cookies.values())
    assert verified.status_code == 200
    await client.post("/v1/auth/refresh", headers={"X-CSRF-Token": client.cookies["mo_csrf"]})
    confidential_values.extend(client.cookies.values())
    failure = await client.post(
        "/v1/auth/password/change",
        headers={"X-CSRF-Token": client.cookies["mo_csrf"]},
        json={"currentPassword": "incorrect", "newPassword": password},
    )
    assert failure.status_code == 401
    start = await client.get("/v1/auth/oauth/google/start")
    provider = await client.get(start.headers["location"])
    await client.get(provider.headers["location"])
    captured = capfd.readouterr()
    output = captured.out + captured.err + "".join(event.model_dump_json() for event in auth_state.audit) + failure.text
    for value in confidential_values:
        assert value not in output
    assert any(event.action == "auth.change_password.rejected" for event in auth_state.audit)
