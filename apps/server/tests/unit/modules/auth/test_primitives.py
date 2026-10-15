from datetime import timedelta
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.responses import Response
from tests.fakes.auth import AuthState
from tests.unit.modules.auth.test_auth import clear_cooldown, registered

from motionile.core.errors import UnauthorizedError, ValidationAppError
from motionile.core.security.cookies import CookieManager, SessionCookies
from motionile.core.security.identifiers import normalize_identifier
from motionile.core.security.tokens import base64url, token_hash
from motionile.modules.auth.oauth.fake import FakeGrant, FakeOAuthProvider
from motionile.modules.auth.oauth.providers import ProviderIdentity, ProviderName, verified_email
from motionile.modules.auth.oauth.service import OAuthService, relative_next
from motionile.modules.auth.service import AuthService
from motionile.modules.notifications.rendering import render_email
from motionile.modules.notifications.schemas import Notification


@pytest.mark.parametrize(
    ("value", "normalized", "masked"),
    [
        (" Rishabh@EXAMPLE.COM ", "rishabh@example.com", "r•••@e•••.com"),
        ("+91 98765 43210", "+919876543210", "+91 •••••• 3210"),
    ],
)
def test_identifiers(value: str, normalized: str, masked: str) -> None:
    identifier = normalize_identifier(value)
    assert identifier.value == normalized
    assert identifier.masked == masked


@pytest.mark.parametrize("value", ["bad", "x@@example.com", "+1", "+91 1123456789"])
def test_invalid_identifiers(value: str) -> None:
    with pytest.raises(ValidationAppError):
        normalize_identifier(value)


async def test_password_policy_and_dummy_verification(auth_service: AuthService) -> None:
    passwords = auth_service.runtime.passwords
    for value in ("short", "x" * 129):
        with pytest.raises(ValidationAppError):
            await passwords.validate(value)
    phrase = "long enough passphrase"
    encoded = await passwords.hash(phrase)
    assert encoded.startswith("$argon2id$")
    assert await passwords.verify(phrase, encoded)
    assert not await passwords.verify("wrong", encoded)
    assert not await passwords.verify(phrase, None)


async def test_cookie_attributes_and_clear_scopes(auth_service: AuthService) -> None:
    manager = CookieManager(".motionile.com")
    now = auth_service.resources.clock.now()
    response = Response()
    manager.set_session(
        response,
        SessionCookies(
            access="access",
            refresh="refresh",
            csrf="csrf",
            expires_at=now + timedelta(minutes=15),
            refresh_max_age=604800,
        ),
    )
    manager.set_ticket(response, "ticket")
    manager.set_oauth(response, "binding")
    parsed: SimpleCookie = SimpleCookie()
    for value in response.headers.getlist("set-cookie"):
        parsed.load(value)
    for value in parsed.values():
        assert value["secure"]
    for name in ("__Secure-mo_at", "__Secure-mo_rt", "__Secure-mo_vt", "__Secure-mo_oauth"):
        assert parsed[name]["httponly"]
    for name in ("mo_csrf", "mo_auth"):
        assert not parsed[name]["httponly"]
        assert parsed[name]["domain"] == ".motionile.com"
    assert parsed["__Secure-mo_rt"]["path"] == "/v1/auth"
    assert parsed["__Secure-mo_rt"]["domain"] == ""
    assert parsed["__Secure-mo_rt"]["samesite"] == "strict"
    assert parsed["__Secure-mo_oauth"]["samesite"] == "lax"
    assert parsed["__Secure-mo_at"]["max-age"] == "900"
    cleared = Response()
    manager.clear(cleared)
    for value in cleared.headers.getlist("set-cookie"):
        entry: SimpleCookie = SimpleCookie()
        entry.load(value)
        for name, cookie in entry.items():
            assert cookie["path"] == parsed[name]["path"]
            assert cookie["domain"] == parsed[name]["domain"]
            assert cookie["max-age"] == "0"


@pytest.mark.parametrize(
    ("provider", "claims", "expected"),
    [
        ("google", {"email_verified": True}, True),
        ("google", {"email_verified": "true"}, False),
        ("github", {"primary": True, "verified": True}, True),
        ("github", {"primary": False, "verified": True}, False),
        ("microsoft", {"tid": "9188040d-6c67-4c5b-b112-36a304b66dad"}, True),
        ("microsoft", {"xms_edov": True}, True),
        ("microsoft", {"email_verified": True}, False),
    ],
)
def test_verified_email_rules(provider: ProviderName, claims: dict[str, object], expected: bool) -> None:
    assert verified_email(provider, claims) == expected


@pytest.mark.parametrize(
    "value", ["https://evil.example", "//evil.example", "/%2fexample.com", "/%255cevil.example", "/%0d%0aLocation:evil"]
)
def test_redirect_rejection(value: str) -> None:
    with pytest.raises(ValidationAppError):
        relative_next(value)


async def test_fake_provider_pkce_nonce_and_single_use(auth_service: AuthService) -> None:
    provider = FakeOAuthProvider("google", "https://localhost:8000", auth_service.resources.redis_store)
    grant = FakeGrant(
        challenge=base64url(token_hash("verifier")),
        nonce="nonce",
        identity=ProviderIdentity(subject="1", email="oauth@example.com", email_verified=True),
    )
    location = await provider.authorize("state", grant)
    code = location.split("code=", 1)[1]
    with pytest.raises(UnauthorizedError):
        await provider.exchange_code(code, "wrong-verifier")
    location = await provider.authorize("state", grant)
    code = location.split("code=", 1)[1]
    tokens = await provider.exchange_code(code, "verifier")
    with pytest.raises(UnauthorizedError):
        await provider.fetch_identity(tokens, "wrong-nonce")
    assert (await provider.fetch_identity(tokens, "nonce")).subject == "1"
    with pytest.raises(UnauthorizedError):
        await provider.exchange_code(code, "verifier")


async def test_oauth_state_browser_binding_and_replay(auth_service: AuthService) -> None:
    service = OAuthService(auth_service)
    location, browser = await service.start("google", "/dashboard", "login", None)
    state = parse_qs(urlsplit(location).query)["state"][0]
    with pytest.raises(UnauthorizedError):
        await service.consume_state("google", state, "attacker")
    location, browser = await service.start("google", "/dashboard", "login", None)
    state = parse_qs(urlsplit(location).query)["state"][0]
    payload = await service.consume_state("google", state, browser)
    assert payload.next_path == "/dashboard"
    with pytest.raises(UnauthorizedError):
        await service.consume_state("google", state, browser)


def test_email_templates_are_signed_and_do_not_inject_html() -> None:
    rendered = render_email(
        Notification(destination="mail@example.com", channel="email", template="login", code="<script>")
    )
    assert "Motionile" in rendered.text
    assert "<script>" not in rendered.html
    assert "&lt;script&gt;" in rendered.html


async def test_request_and_register_shapes_do_not_enumerate(auth_service: AuthService, auth_state: AuthState) -> None:
    await registered(auth_service, auth_state)
    await clear_cooldown(auth_service)
    _, existing = await auth_service.register(
        "Existing", normalize_identifier("rishabh@example.com"), "a-safe-test-passphrase"
    )
    _, absent = await auth_service.register("New", normalize_identifier("random@example.com"), "a-safe-test-passphrase")
    assert existing == absent
    for purpose in ("login", "password_reset"):
        await clear_cooldown(auth_service)
        await clear_cooldown(auth_service, "random@example.com")
        _, existing = await auth_service.request_otp(normalize_identifier("rishabh@example.com"), purpose)
        _, absent = await auth_service.request_otp(normalize_identifier("random@example.com"), purpose)
        assert existing == absent
    assert all("password" not in event.metadata and "code" not in event.metadata for event in auth_state.audit)
