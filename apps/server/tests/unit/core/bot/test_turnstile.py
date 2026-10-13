import ipaddress
from dataclasses import dataclass, field
from typing import Annotated

import httpx
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from motionile.core.bot.turnstile import (
    TURNSTILE_HEADER,
    CloudflareTurnstileVerifier,
    FakeTurnstileVerifier,
    TurnstileResult,
    TurnstileVerifier,
    require_turnstile,
)
from motionile.core.config import OutboundHttpSettings
from motionile.core.errors import ServiceUnavailableError, register_exception_handlers
from motionile.core.http.safe_client import IPAddress, SafeHttpClient

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TEST_SECRET = "1x0000000000000000000000000000000AA"  # noqa: S105


async def cloudflare_dns(_host: str, _port: int) -> list[IPAddress]:
    return [ipaddress.ip_address("104.16.0.1")]


@dataclass
class SiteverifyStub:
    payload: dict[str, object]
    status: int = 200
    requests: list[httpx.Request] = field(default_factory=list[httpx.Request])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json=self.payload)


def verifier_for(stub: SiteverifyStub) -> CloudflareTurnstileVerifier:
    client = SafeHttpClient(OutboundHttpSettings(), resolver=cloudflare_dns, transport=httpx.MockTransport(stub))
    return CloudflareTurnstileVerifier(
        client, secret_key=TEST_SECRET, verify_url=VERIFY_URL, expected_hostnames=("motionile.com",)
    )


async def test_cloudflare_verifier_accepts_matching_response() -> None:
    stub = SiteverifyStub({"success": True, "hostname": "motionile.com", "action": "signup"})

    result = await verifier_for(stub).verify("token", remote_ip="203.0.113.9", action="signup")

    assert result.success
    form = dict(httpx.QueryParams(stub.requests[0].content.decode()))
    assert form == {"secret": TEST_SECRET, "response": "token", "remoteip": "203.0.113.9"}


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        ({"success": False, "error-codes": ["invalid-input-response"]}, "invalid-input-response"),
        ({"success": True, "hostname": "evil.example", "action": "signup"}, "hostname-mismatch"),
        ({"success": True, "hostname": "motionile.com", "action": "login"}, "action-mismatch"),
    ],
)
async def test_cloudflare_verifier_rejects_mismatches(payload: dict[str, object], error_code: str) -> None:
    result = await verifier_for(SiteverifyStub(payload)).verify("token", remote_ip=None, action="signup")

    assert not result.success
    assert error_code in result.error_codes


async def test_cloudflare_verifier_omits_missing_remote_ip() -> None:
    stub = SiteverifyStub({"success": True, "hostname": "motionile.com", "action": "signup"})

    await verifier_for(stub).verify("token", remote_ip=None, action="signup")

    assert "remoteip" not in dict(httpx.QueryParams(stub.requests[0].content.decode()))


async def test_cloudflare_verifier_fails_closed_on_garbage() -> None:
    stub = SiteverifyStub({"unexpected": True})

    with pytest.raises(ServiceUnavailableError) as raised:
        await verifier_for(stub).verify("token", remote_ip=None, action="signup")

    assert raised.value.code == "turnstile_unavailable"


async def test_fake_verifier_fails_tokens_with_failing_prefix() -> None:
    fake = FakeTurnstileVerifier()

    passing = await fake.verify("pass-token", remote_ip="203.0.113.1", action="signup")
    failing = await fake.verify("fail-token", remote_ip=None, action="signup")

    assert passing.success
    assert not failing.success
    assert isinstance(fake, TurnstileVerifier)


@dataclass
class TurnstileState:
    turnstile: object


def build_app(verifier: object) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.state.resources = TurnstileState(verifier)

    @app.post("/signup")
    async def signup(result: Annotated[TurnstileResult, Depends(require_turnstile("signup"))]) -> dict[str, str]:
        return {"action": result.action or ""}

    return app


async def post_signup(app: FastAPI, headers: dict[str, str]) -> httpx.Response:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        return await http.post("/signup", headers=headers)


async def test_dependency_requires_the_token_header() -> None:
    response = await post_signup(build_app(FakeTurnstileVerifier()), {})

    assert response.status_code == 400
    assert response.json()["code"] == "turnstile_required"


async def test_dependency_rejects_failed_tokens() -> None:
    response = await post_signup(build_app(FakeTurnstileVerifier()), {TURNSTILE_HEADER: "fail-me"})

    assert response.status_code == 403
    assert response.json()["code"] == "turnstile_failed"


async def test_dependency_rejects_oversized_tokens() -> None:
    response = await post_signup(build_app(FakeTurnstileVerifier()), {TURNSTILE_HEADER: "x" * 4096})

    assert response.status_code == 403


async def test_dependency_passes_action_and_client_ip() -> None:
    fake = FakeTurnstileVerifier()

    response = await post_signup(build_app(fake), {TURNSTILE_HEADER: "good"})

    assert response.status_code == 200
    assert response.json() == {"action": "signup"}
    assert fake.last_remote_ip == "127.0.0.1"


async def test_dependency_requires_a_configured_verifier() -> None:
    with pytest.raises(TypeError, match="not configured"):
        await post_signup(build_app(object()), {TURNSTILE_HEADER: "good"})
