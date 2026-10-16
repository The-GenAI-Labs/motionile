import asyncio
import secrets
from datetime import timedelta
from uuid import UUID

import jwt
import pytest
from tests.fakes.auth import AuthState

from motionile.core.clock import FrozenClock
from motionile.core.errors import AppError, ForbiddenError, NotFoundError, RateLimitedError, UnauthorizedError
from motionile.core.security.cookies import SessionCookies
from motionile.core.security.csrf import CsrfError
from motionile.core.security.identifiers import normalize_identifier
from motionile.core.security.rbac import Principal
from motionile.core.security.tokens import token_hash
from motionile.modules.auth.exceptions import VerificationRequiredError
from motionile.modules.auth.schemas import SessionUser
from motionile.modules.auth.service import AuthService

PASSPHRASE = secrets.token_urlsafe(24)
REPLACEMENT = "Motionile-replacement-passphrase-2026"
EMAIL = "rishabh@example.com"


async def clear_cooldown(service: AuthService, destination: str = EMAIL) -> None:
    store = service.resources.redis_store
    await store.delete(store.keys.key("otp.cooldown", token_hash(destination).hex()))


async def registered(service: AuthService, state: AuthState, email: str = EMAIL) -> tuple[SessionUser, SessionCookies]:
    ticket, _ = await service.register("Rishabh", normalize_identifier(email), PASSPHRASE)
    code = state.notifications[-1].code
    assert code is not None
    return await service.verify_contact(ticket, code)


async def principal(service: AuthService, cookies: SessionCookies) -> Principal:
    return await service.runtime.tokens.verify(cookies.access)


async def test_registration_verification_and_logout(auth_service: AuthService, auth_state: AuthState) -> None:
    user, cookies = await registered(auth_service, auth_state)
    identity = await principal(auth_service, cookies)
    assert user.roles == ["user"]
    assert user.status == "active"
    assert EMAIL not in user.model_dump_json()
    assert user.has_password
    assert (await auth_service.me(identity)).id == user.id
    assert len((await auth_service.sessions(identity)).items) == 1
    await auth_service.logout(identity)
    with pytest.raises(UnauthorizedError):
        await auth_service.runtime.tokens.verify(cookies.access)
    assert all(row.revoked_at is not None for row in auth_state.sessions.values())


async def test_short_access_lifetime_matches_token_and_cookies(
    auth_service: AuthService, auth_state: AuthState, auth_clock: FrozenClock
) -> None:
    settings = auth_service.resources.settings
    auth_settings = settings.auth.model_copy(update={"test_access_seconds": 75})
    auth_service.resources.settings = settings.model_copy(update={"auth": auth_settings})
    auth_service.runtime.tokens.settings = auth_settings
    _, cookies = await registered(auth_service, auth_state)
    claims = auth_service.runtime.tokens.decode(cookies.access)
    assert claims.exp - claims.iat == 75
    assert cookies.access_max_age == 75
    assert cookies.expires_at == auth_clock.now() + timedelta(seconds=75)
    auth_clock.advance(timedelta(seconds=81))
    with pytest.raises(UnauthorizedError) as expired:
        await principal(auth_service, cookies)
    assert expired.value.code == "token_expired"
    refreshed = await auth_service.refresh(cookies.refresh, cookies.csrf, cookies.csrf)
    assert refreshed.access_max_age == 75
    assert refreshed.expires_at == auth_clock.now() + timedelta(seconds=75)
    await principal(auth_service, refreshed)


async def test_refresh_grace_then_reuse_denies_access(
    auth_service: AuthService, auth_state: AuthState, auth_clock: FrozenClock
) -> None:
    _, original = await registered(auth_service, auth_state)
    successor = await auth_service.refresh(original.refresh, original.csrf, original.csrf)
    assert successor.refresh != original.refresh
    assert (await principal(auth_service, successor)).session_id == (await principal(auth_service, original)).session_id
    with pytest.raises(UnauthorizedError) as conflict:
        await auth_service.refresh(original.refresh, original.csrf, original.csrf)
    assert conflict.value.code == "refresh_conflict"
    assert all(row.revoked_at is None for row in auth_state.sessions.values())
    auth_clock.advance(timedelta(seconds=11))
    with pytest.raises(UnauthorizedError) as reuse:
        await auth_service.refresh(original.refresh, original.csrf, original.csrf)
    assert reuse.value.code == "refresh_reused"
    with pytest.raises(UnauthorizedError):
        await principal(auth_service, successor)
    assert all(row.revoke_reason == "reuse_detected" for row in auth_state.sessions.values())
    assert any(message.template == "refresh_reuse" for message in auth_state.notifications)


async def test_concurrent_refresh_has_one_successor(auth_service: AuthService, auth_state: AuthState) -> None:
    _, cookies = await registered(auth_service, auth_state)
    results = await asyncio.gather(
        *(auth_service.refresh(cookies.refresh, cookies.csrf, cookies.csrf) for _ in range(2)), return_exceptions=True
    )
    assert sum(isinstance(result, SessionCookies) for result in results) == 1
    assert sum(isinstance(result, UnauthorizedError) and result.code == "refresh_conflict" for result in results) == 1
    assert len(auth_state.sessions) == 2


@pytest.mark.parametrize("expiry", ["idle_expires_at", "absolute_expires_at"])
async def test_session_expiry(
    auth_service: AuthService, auth_state: AuthState, auth_clock: FrozenClock, expiry: str
) -> None:
    _, cookies = await registered(auth_service, auth_state)
    row = next(iter(auth_state.sessions.values()))
    setattr(row, expiry, auth_clock.now())
    with pytest.raises(UnauthorizedError) as error:
        await auth_service.refresh(cookies.refresh, cookies.csrf, cookies.csrf)
    assert error.value.code == "session_expired"


async def test_refresh_caps_idle_at_absolute(
    auth_service: AuthService, auth_state: AuthState, auth_clock: FrozenClock
) -> None:
    _, cookies = await registered(auth_service, auth_state)
    row = next(iter(auth_state.sessions.values()))
    row.absolute_expires_at = auth_clock.now() + timedelta(days=2)
    refreshed = await auth_service.refresh(cookies.refresh, cookies.csrf, cookies.csrf)
    assert refreshed.refresh_max_age == 2 * 86400
    assert list(auth_state.sessions.values())[-1].idle_expires_at == row.absolute_expires_at


async def test_unverified_login_sets_challenge(auth_service: AuthService, auth_state: AuthState) -> None:
    await auth_service.register("Rishabh", normalize_identifier(EMAIL), PASSPHRASE)
    await clear_cooldown(auth_service)
    with pytest.raises(VerificationRequiredError) as error:
        await auth_service.password_login(normalize_identifier(EMAIL), PASSPHRASE)
    code = auth_state.notifications[-1].code
    assert code is not None
    user, _ = await auth_service.verify_contact(error.value.ticket, code)
    assert user.status == "active"


async def test_login_failures_do_not_enumerate(auth_service: AuthService, auth_state: AuthState) -> None:
    await registered(auth_service, auth_state)
    errors: list[tuple[int, str, str | None]] = []
    for email in (EMAIL, "absent@example.com"):
        with pytest.raises(UnauthorizedError) as caught:
            await auth_service.password_login(normalize_identifier(email), "wrong-password")
        errors.append((caught.value.status_code, caught.value.code, caught.value.detail))
    assert errors[0] == errors[1]


async def test_lockout_otp_bypass_and_unlock(auth_service: AuthService, auth_state: AuthState) -> None:
    await registered(auth_service, auth_state)
    for _ in range(10):
        with pytest.raises(UnauthorizedError):
            await auth_service.password_login(normalize_identifier(EMAIL), "wrong-password")
    with pytest.raises(UnauthorizedError):
        await auth_service.password_login(normalize_identifier(EMAIL), PASSPHRASE)
    await clear_cooldown(auth_service)
    ticket, _ = await auth_service.request_otp(normalize_identifier(EMAIL), "login")
    code = auth_state.notifications[-1].code
    assert code is not None
    user, _ = await auth_service.otp_login(ticket, code)
    store = auth_service.resources.redis_store
    key = store.keys.key("auth.lockout", token_hash(EMAIL).hex())
    assert 0 < await store.client.ttl(key) <= 900
    await store.delete(key)
    signed_in, _ = await auth_service.password_login(normalize_identifier(EMAIL), PASSPHRASE)
    assert signed_in.id == user.id
    assert sum(message.template == "password_lockout" for message in auth_state.notifications) == 1


async def test_password_change_keeps_only_current_family(auth_service: AuthService, auth_state: AuthState) -> None:
    _, first = await registered(auth_service, auth_state)
    _, second = await auth_service.password_login(normalize_identifier(EMAIL), PASSPHRASE)
    await auth_service.change_password(await principal(auth_service, first), PASSPHRASE, REPLACEMENT)
    await principal(auth_service, first)
    with pytest.raises(UnauthorizedError):
        await principal(auth_service, second)
    await auth_service.password_login(normalize_identifier(EMAIL), REPLACEMENT)


async def test_password_reset_revokes_all_families(auth_service: AuthService, auth_state: AuthState) -> None:
    _, first = await registered(auth_service, auth_state)
    _, second = await auth_service.password_login(normalize_identifier(EMAIL), PASSPHRASE)
    await clear_cooldown(auth_service)
    ticket, _ = await auth_service.request_otp(normalize_identifier(EMAIL), "password_reset")
    code = auth_state.notifications[-1].code
    assert code is not None
    await auth_service.reset_password(ticket, code, REPLACEMENT)
    for cookies in (first, second):
        with pytest.raises(UnauthorizedError):
            await principal(auth_service, cookies)


async def test_owned_session_revoke_only(auth_service: AuthService, auth_state: AuthState) -> None:
    _, first = await registered(auth_service, auth_state)
    _, other = await registered(auth_service, auth_state, "other@example.com")
    owner = await principal(auth_service, first)
    foreign = await principal(auth_service, other)
    with pytest.raises(NotFoundError):
        await auth_service.logout(owner, family_id=foreign.session_id)
    await principal(auth_service, other)


async def test_suspended_and_deleted_accounts(
    auth_service: AuthService, auth_state: AuthState, auth_clock: FrozenClock
) -> None:
    user, _ = await registered(auth_service, auth_state)
    auth_state.users[user.id].status = "suspended"
    with pytest.raises(ForbiddenError) as error:
        await auth_service.password_login(normalize_identifier(EMAIL), PASSPHRASE)
    assert error.value.code == "account_suspended"
    auth_state.users[user.id].deleted_at = auth_clock.now()
    auth_state.users[user.id].status = "deleted"
    with pytest.raises(UnauthorizedError) as deleted:
        await auth_service.password_login(normalize_identifier(EMAIL), PASSPHRASE)
    assert deleted.value.code == "invalid_credentials"


async def test_csrf_bound_to_family(auth_service: AuthService, auth_state: AuthState) -> None:
    _, first = await registered(auth_service, auth_state)
    _, second = await auth_service.password_login(normalize_identifier(EMAIL), PASSPHRASE)
    for cookie, header in ((None, None), (first.csrf, "wrong"), (second.csrf, second.csrf)):
        with pytest.raises(CsrfError):
            await auth_service.refresh(first.refresh, cookie, header)


async def test_jwt_tampering_and_expiry(
    auth_service: AuthService, auth_state: AuthState, auth_clock: FrozenClock
) -> None:
    _, cookies = await registered(auth_service, auth_state)
    claims = jwt.decode(cookies.access, options={"verify_signature": False})
    tokens = auth_service.runtime.tokens
    altered = cookies.access[:-8] + "AAAAAAAA"
    for forged in (
        altered,
        jwt.encode(claims, "", algorithm="none"),
        jwt.encode(claims, tokens.keys["local"], algorithm="EdDSA", headers={"kid": "wrong"}),
    ):
        with pytest.raises(UnauthorizedError):
            await tokens.verify(forged)
    claims["aud"] = "other"
    wrong_audience = jwt.encode(claims, tokens.keys["local"], algorithm="EdDSA", headers={"kid": "local"})
    with pytest.raises(UnauthorizedError):
        await tokens.verify(wrong_audience)
    auth_clock.advance(timedelta(seconds=906))
    with pytest.raises(UnauthorizedError) as error:
        await tokens.verify(cookies.access)
    assert error.value.code == "token_expired"


async def test_otp_atomic_single_use_and_attempt_exhaustion(auth_service: AuthService) -> None:
    otp = auth_service.runtime.otp
    ticket, challenge, code = await otp.issue("login", normalize_identifier(EMAIL), UUID(int=1))
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        with pytest.raises(UnauthorizedError):
            await otp.verify(ticket, "login", wrong)
    assert await otp.store.get(otp.challenge_key(challenge.id)) is None
    await clear_cooldown(auth_service)
    ticket, _, code = await otp.issue("login", normalize_identifier(EMAIL), UUID(int=1))
    results = await asyncio.gather(
        otp.verify(ticket, "login", code), otp.verify(ticket, "login", code), return_exceptions=True
    )
    assert sum(isinstance(result, AppError) for result in results) == 1


async def test_resend_cooldown_and_purpose_binding(auth_service: AuthService) -> None:
    otp = auth_service.runtime.otp
    ticket, _, code = await otp.issue("login", normalize_identifier(EMAIL), UUID(int=1))
    with pytest.raises(RateLimitedError):
        await auth_service.resend(ticket)
    with pytest.raises(UnauthorizedError):
        await otp.verify(ticket, "password_reset", code)
    await clear_cooldown(auth_service)
    replacement, _ = await auth_service.resend(ticket)
    assert replacement != ticket
    with pytest.raises(UnauthorizedError):
        await otp.verify(ticket, "login", code)


async def test_resend_survives_code_expiry(auth_service: AuthService) -> None:
    otp = auth_service.runtime.otp
    ticket, challenge, code = await otp.issue("login", normalize_identifier(EMAIL), UUID(int=1))
    await otp.store.delete(otp.challenge_key(challenge.id))
    await clear_cooldown(auth_service)
    replacement, response = await auth_service.resend(ticket)
    assert replacement != ticket
    assert response.expires_in == 300
    with pytest.raises(UnauthorizedError):
        await otp.verify(ticket, "login", code)


async def test_logout_all_denies_access_even_when_refresh_expired(
    auth_service: AuthService, auth_state: AuthState, auth_clock: FrozenClock
) -> None:
    _, cookies = await registered(auth_service, auth_state)
    identity = await principal(auth_service, cookies)
    row = next(iter(auth_state.sessions.values()))
    row.idle_expires_at = auth_clock.now()
    row.absolute_expires_at = auth_clock.now()
    await auth_service.logout(identity, everywhere=True)
    with pytest.raises(UnauthorizedError):
        await principal(auth_service, cookies)
