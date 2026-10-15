import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from pydantic import SecretStr

from motionile.core.config import AuthSettings, NotificationSettings, OutboundHttpSettings
from motionile.core.errors import UnauthorizedError
from motionile.core.http.safe_client import IPAddress, SafeHttpClient
from motionile.core.security.passwords import Passwords
from motionile.modules.auth.oauth.providers import LiveOAuthProvider, ProviderName
from motionile.modules.auth.service import AuthService
from motionile.modules.notifications.providers import MetaWhatsAppSender


async def public_resolver(host: str, port: int) -> list[IPAddress]:
    del host, port
    return [IPv4Address("93.184.216.34")]


async def test_whatsapp_authentication_and_notice_request_contract() -> None:
    requests: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"messages": [{"id": "test-message"}]})

    client = SafeHttpClient(
        OutboundHttpSettings(),
        resolver=public_resolver,
        allowed_hosts={"graph.facebook.com"},
        transport=httpx.MockTransport(capture),
    )
    settings = NotificationSettings(
        whatsapp_token=SecretStr("fake-provider-secret"),
        whatsapp_phone_number_id="123456789",
        whatsapp_template="motionile_code",
        whatsapp_notice_template="motionile_security_notice",
        whatsapp_language="en_US",
        whatsapp_api_version="v25.0",
    )
    try:
        sender = MetaWhatsAppSender(settings, client)
        await sender.send("+919876543210", "482193")
        await sender.send_notice("+919876543210", "Your password changed. Motionile")
    finally:
        await client.aclose()
    request = requests[0]
    assert request.method == "POST"
    assert request.headers["host"] == "graph.facebook.com"
    assert request.url.path == "/v25.0/123456789/messages"
    assert request.headers["authorization"] == "Bearer fake-provider-secret"
    assert json.loads(request.content) == {
        "messaging_product": "whatsapp",
        "to": "919876543210",
        "type": "template",
        "template": {
            "name": "motionile_code",
            "language": {"code": "en_US"},
            "components": [
                {"type": "body", "parameters": [{"type": "text", "text": "482193"}]},
                {"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": "482193"}]},
            ],
        },
    }
    assert json.loads(requests[1].content)["template"] == {
        "name": "motionile_security_notice",
        "language": {"code": "en_US"},
        "components": [{"type": "body", "parameters": [{"type": "text", "text": "Your password changed. Motionile"}]}],
    }


@pytest.mark.parametrize("provider", ["google", "microsoft"])
async def test_signed_oidc_claims_and_jwks_cache(auth_service: AuthService, provider: ProviderName) -> None:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    tenant = "9188040d-6c67-4c5b-b112-36a304b66dad"
    issuer = (
        "https://accounts.google.com" if provider == "google" else f"https://login.microsoftonline.com/{tenant}/v2.0"
    )
    public = json.loads(RSAAlgorithm.to_jwk(private.public_key()))
    public.update(kid="test-key", use="sig", issuer="https://login.microsoftonline.com/{tenantid}/v2.0")
    requests: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"keys": [public]})

    client = SafeHttpClient(OutboundHttpSettings(), resolver=public_resolver, transport=httpx.MockTransport(capture))
    adapter = LiveOAuthProvider(
        provider,
        AuthSettings(google_client_id="client", microsoft_client_id="client"),
        client,
        auth_service.resources.redis_store,
    )
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "sub": "subject",
        "iss": issuer,
        "aud": "client",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "nonce": "browser-nonce",
        "tid": tenant,
    }

    def signed(overrides: Mapping[str, object]) -> str:
        return jwt.encode({**claims, **overrides}, private, algorithm="RS256", headers={"kid": "test-key"})

    try:
        assert (await adapter.verify_id_token(signed({}), "browser-nonce"))["sub"] == "subject"
        for overrides in (
            {"nonce": "other"},
            {"aud": "other"},
            {"iss": "https://attacker.example"},
            {"exp": int((now - timedelta(minutes=1)).timestamp())},
            {"azp": "other"},
        ):
            with pytest.raises((UnauthorizedError, jwt.InvalidTokenError)):
                await adapter.verify_id_token(signed(overrides), "browser-nonce")
        assert len(requests) == 1
        if provider == "microsoft":
            public["issuer"] = "https://login.microsoftonline.com/00000000-0000-0000-0000-000000000001/v2.0"
            await auth_service.resources.redis_store.delete(
                auth_service.resources.redis_store.keys.key("oauth.jwks", provider)
            )
            with pytest.raises(UnauthorizedError):
                await adapter.verify_id_token(signed({}), "browser-nonce")
    finally:
        await client.aclose()


@pytest.mark.parametrize(("status", "breached"), [(200, True), (503, False)])
async def test_hibp_range_privacy_and_fail_open(status: int, *, breached: bool) -> None:
    phrase = "test-only-breach-passphrase"
    digest = hashlib.sha1(phrase.encode(), usedforsecurity=False).hexdigest().upper()
    requests: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, text=digest[5:] + ":42\r\n")

    client = SafeHttpClient(OutboundHttpSettings(), resolver=public_resolver, transport=httpx.MockTransport(capture))
    try:
        assert await Passwords(client, check_breaches=True).is_breached(phrase) is breached
    finally:
        await client.aclose()
    assert requests[0].url.path == "/range/" + digest[:5]
    assert requests[0].headers["add-padding"] == "true"
    assert not requests[0].content
    assert phrase not in str(requests[0].url)
