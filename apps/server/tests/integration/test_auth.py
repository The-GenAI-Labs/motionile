import asyncio
import secrets
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import FrozenClock
from motionile.core.db import after_commit
from motionile.core.resources import Resources
from motionile.core.security.cookies import CSRF_COOKIE
from motionile.core.security.tokens import token_hash
from motionile.entrypoints.api import create_app
from motionile.modules.auth import AuthRuntime
from motionile.modules.auth import service as auth_module
from motionile.modules.notifications import FakeDelivery, Notification

PASSPHRASE = secrets.token_urlsafe(24)


@pytest.fixture
async def auth_client(resources: Resources, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    resources.rate_limiter.enabled = False
    resources.clock = FrozenClock(resources.clock.now())
    inbox = FakeDelivery(resources.redis_store)

    def enqueue(fake_resources: Resources, session: AsyncSession, message: Notification) -> None:
        del fake_resources

        async def deliver() -> None:
            await inbox.record(message)

        after_commit(session, deliver)

    monkeypatch.setattr(auth_module, "enqueue_notification", enqueue)
    app = create_app(resources.settings, resources=resources)
    app.state.auth_runtime = AuthRuntime(resources)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://localhost:8000",
        headers={"Origin": "http://localhost:3000", "X-Turnstile-Token": "test-pass"},
    ) as client:
        yield client
    async with resources.database.transaction() as session:
        await session.execute(text("SET LOCAL motionile.allow_purge = 'on'"))
        await session.execute(text("DELETE FROM audit_log WHERE action LIKE 'auth.%'"))
        await session.execute(text("DELETE FROM users"))


async def read_code(client: AsyncClient, email: str) -> str:
    response = await client.get(f"/v1/_test/inbox/{email}")
    messages = response.json()["messages"]
    return next(str(message["code"]) for message in messages if message.get("code"))


async def signup(client: AsyncClient, email: str = "integration@example.com") -> str:
    registration = await client.post(
        "/v1/auth/register", json={"name": "Integration", "email": email, "password": PASSPHRASE}
    )
    assert registration.status_code == 202, registration.text
    verification = await client.post("/v1/auth/verify", json={"code": await read_code(client, email)})
    assert verification.status_code == 200, verification.text
    return str(verification.json()["id"])


def csrf(client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies[CSRF_COOKIE]}


async def clear_cooldowns(resources: Resources) -> None:
    await resources.redis_store.delete(
        resources.redis_store.keys.key("otp.cooldown", token_hash("integration@example.com").hex())
    )


async def test_register_verify_me_refresh_logout(auth_client: AsyncClient) -> None:
    user_id = await signup(auth_client)
    assert (await auth_client.get("/v1/auth/me")).json()["id"] == user_id
    assert (await auth_client.post("/v1/auth/refresh", headers=csrf(auth_client))).status_code == 204
    sessions = await auth_client.get("/v1/auth/sessions")
    assert len(sessions.json()["items"]) == 1
    assert (await auth_client.post("/v1/auth/logout", headers=csrf(auth_client))).status_code == 204
    assert (await auth_client.get("/v1/auth/me")).status_code == 401


async def test_parallel_refresh_then_reuse(auth_client: AsyncClient, resources: Resources) -> None:
    await signup(auth_client)
    original = dict(auth_client.cookies)
    headers = {
        "Cookie": "; ".join(f"{name}={value}" for name, value in original.items()),
        "X-CSRF-Token": original[CSRF_COOKIE],
    }
    responses = await asyncio.gather(*(auth_client.post("/v1/auth/refresh", headers=headers) for _ in range(2)))
    assert sorted(response.status_code for response in responses) == [204, 401]
    conflict = next(response for response in responses if response.status_code == 401)
    assert conflict.json()["code"] == "refresh_conflict"
    assert isinstance(resources.clock, FrozenClock)
    resources.clock.advance(timedelta(seconds=11))
    reuse = await auth_client.post("/v1/auth/refresh", headers=headers)
    assert reuse.json()["code"] == "refresh_reused"
    assert (await auth_client.get("/v1/auth/me")).status_code == 401


async def test_otp_reset_and_change_password(auth_client: AsyncClient, resources: Resources) -> None:
    await signup(auth_client)
    assert (await auth_client.post("/v1/auth/logout", headers=csrf(auth_client))).status_code == 204
    await clear_cooldowns(resources)
    assert (
        await auth_client.post("/v1/auth/otp/request", json={"identifier": "integration@example.com"})
    ).status_code == 202
    assert (
        await auth_client.post(
            "/v1/auth/otp/verify", json={"code": await read_code(auth_client, "integration@example.com")}
        )
    ).status_code == 200
    changed = await auth_client.post(
        "/v1/auth/password/change",
        headers=csrf(auth_client),
        json={"currentPassword": PASSPHRASE, "newPassword": "changed-integration-passphrase"},
    )
    assert changed.status_code == 204
    await clear_cooldowns(resources)
    assert (
        await auth_client.post("/v1/auth/password/forgot", json={"identifier": "integration@example.com"})
    ).status_code == 202
    reset = await auth_client.post(
        "/v1/auth/password/reset",
        json={
            "code": await read_code(auth_client, "integration@example.com"),
            "newPassword": "reset-integration-passphrase",
        },
    )
    assert reset.status_code == 204
    assert (await auth_client.get("/v1/auth/me")).status_code == 401
    login = await auth_client.post(
        "/v1/auth/login", json={"identifier": "integration@example.com", "password": "reset-integration-passphrase"}
    )
    assert login.status_code == 200


@pytest.mark.parametrize("provider", ["google", "github", "microsoft"])
async def test_oauth_signup_link_unlink_and_password_set(auth_client: AsyncClient, provider: str) -> None:
    start = await auth_client.get(f"/v1/auth/oauth/{provider}/start")
    assert start.status_code == 302
    authorize = await auth_client.get(start.headers["location"])
    callback = await auth_client.get(authorize.headers["location"])
    assert callback.status_code == 302
    assert callback.headers["location"] == "http://localhost:3000/dashboard"
    me = await auth_client.get("/v1/auth/me")
    assert me.json()["linkedProviders"] == [provider]
    assert me.json()["hasPassword"] is False
    requested = await auth_client.post("/v1/auth/password/set/request", headers=csrf(auth_client))
    assert requested.status_code == 202
    set_password = await auth_client.post(
        "/v1/auth/password/set",
        headers=csrf(auth_client),
        json={"code": await read_code(auth_client, "oauth@example.com"), "newPassword": PASSPHRASE},
    )
    assert set_password.status_code == 204
    assert (await auth_client.delete(f"/v1/auth/oauth/{provider}", headers=csrf(auth_client))).status_code == 204
    start = await auth_client.get(f"/v1/auth/oauth/{provider}/start?intent=link", headers=csrf(auth_client))
    authorize = await auth_client.get(start.headers["location"])
    assert (await auth_client.get(authorize.headers["location"])).status_code == 302
    assert (await auth_client.get("/v1/auth/me")).json()["linkedProviders"] == [provider]


async def test_missing_csrf_turnstile_and_foreign_session(auth_client: AsyncClient) -> None:
    no_turnstile = await auth_client.post(
        "/v1/auth/login",
        headers={"X-Turnstile-Token": ""},
        json={"identifier": "absent@example.com", "password": PASSPHRASE},
    )
    assert no_turnstile.status_code == 400
    await signup(auth_client)
    assert (await auth_client.post("/v1/auth/logout")).status_code == 403
    sessions = (await auth_client.get("/v1/auth/sessions")).json()["items"]
    foreign_id = sessions[0]["id"]
    await auth_client.post("/v1/auth/logout", headers=csrf(auth_client))
    await signup(auth_client, "second@example.com")
    assert (await auth_client.delete(f"/v1/auth/sessions/{foreign_id}", headers=csrf(auth_client))).status_code == 404


async def test_unverified_login_and_resend(auth_client: AsyncClient, resources: Resources) -> None:
    registration = await auth_client.post(
        "/v1/auth/register", json={"name": "Pending", "email": "integration@example.com", "password": PASSPHRASE}
    )
    assert registration.status_code == 202
    await clear_cooldowns(resources)
    login = await auth_client.post(
        "/v1/auth/login", json={"identifier": "integration@example.com", "password": PASSPHRASE}
    )
    assert login.status_code == 403
    assert login.json()["code"] == "verification_required"
    assert login.json()["challenge"]["expiresIn"] == 300
    await clear_cooldowns(resources)
    assert (await auth_client.post("/v1/auth/otp/resend")).status_code == 202
    verified = await auth_client.post(
        "/v1/auth/verify", json={"code": await read_code(auth_client, "integration@example.com")}
    )
    assert verified.status_code == 200
    assert (await auth_client.post("/v1/auth/logout-all", headers=csrf(auth_client))).status_code == 204
