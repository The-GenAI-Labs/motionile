import hmac
from datetime import timedelta
from typing import Literal
from urllib.parse import unquote, urlsplit
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.errors import ConflictError, UnauthorizedError, ValidationAppError
from motionile.core.ids import new_id
from motionile.core.security.cookies import SessionCookies
from motionile.core.security.identifiers import normalize_identifier
from motionile.core.security.rbac import Principal
from motionile.core.security.tokens import random_token, token_hash
from motionile.modules.access import assign_default_role
from motionile.modules.auth.events import ContactVerified, OAuthIdentityLinked, UserRegistered
from motionile.modules.auth.models import OAuthIdentity
from motionile.modules.auth.oauth.fake import FakeOAuthProvider
from motionile.modules.auth.oauth.providers import LiveOAuthProvider, OAuthProvider, ProviderIdentity, ProviderName
from motionile.modules.auth.repository import AuthRepository
from motionile.modules.auth.service import AuthService
from motionile.modules.users import User, UsersService

CONTROL_CHARACTER_LIMIT = 32
MAX_REDIRECT_LENGTH = 1024


class OAuthState(BaseModel):
    provider: ProviderName
    verifier: str
    nonce: str
    next_path: str
    intent: Literal["login", "link"]
    user_id: UUID | None
    family_id: UUID | None
    browser_digest: str


def relative_next(value: str) -> str:
    decoded = unquote(unquote(value))
    parts = urlsplit(decoded)
    if not decoded.startswith("/") or decoded.startswith("//") or parts.scheme or parts.netloc:
        raise ValidationAppError(code="invalid_redirect")
    if (
        "\\" in decoded
        or any(ord(char) < CONTROL_CHARACTER_LIMIT for char in decoded)
        or len(value) > MAX_REDIRECT_LENGTH
    ):
        raise ValidationAppError(code="invalid_redirect")
    return value


class OAuthService:
    def __init__(self, auth: AuthService) -> None:
        self.auth = auth
        self.resources = auth.resources

    def provider(self, name: ProviderName) -> OAuthProvider:
        if self.resources.settings.is_fake_providers:
            return FakeOAuthProvider(name, self.resources.settings.auth.api_origin, self.resources.redis_store)
        return LiveOAuthProvider(
            name, self.resources.settings.auth, self.resources.provider_clients[name], self.resources.redis_store
        )

    async def start(
        self, provider: ProviderName, next_path: str, intent: Literal["login", "link"], principal: Principal | None
    ) -> tuple[str, str]:
        if intent == "link" and principal is None:
            raise UnauthorizedError(code="unauthenticated")
        state = random_token()
        browser = random_token()
        payload = OAuthState(
            provider=provider,
            verifier=random_token(),
            nonce=random_token(),
            next_path=relative_next(next_path),
            intent=intent,
            user_id=principal.user_id if principal else None,
            family_id=principal.session_id if principal else None,
            browser_digest=token_hash(browser).hex(),
        )
        url = self.provider(provider).authorization_url(state, payload.verifier, payload.nonce)
        await self.resources.redis_store.set(
            self.resources.redis_store.keys.key("oauth.state", token_hash(state).hex()),
            payload.model_dump_json(),
            ttl=timedelta(minutes=10),
        )
        async with self.resources.database.transaction() as session:
            if intent == "link" and principal:
                await self.auth.principal_user(session, principal)
            await self.auth.audit(session, "oauth.started", principal.user_id if principal else None)
        return url, browser

    async def consume_state(self, provider: ProviderName, state: str, browser: str | None) -> OAuthState:
        if not browser:
            raise UnauthorizedError(code="oauth_state_invalid")
        key = self.resources.redis_store.keys.key("oauth.state", token_hash(state).hex())
        raw = await self.resources.redis_store.client.getdel(key)
        if raw is None:
            raise UnauthorizedError(code="oauth_state_invalid")
        payload = OAuthState.model_validate_json(raw)
        if payload.provider != provider or not hmac.compare_digest(payload.browser_digest, token_hash(browser).hex()):
            raise UnauthorizedError(code="oauth_state_invalid")
        return payload

    async def callback(
        self, provider: ProviderName, state: str, code: str, browser: str | None, principal: Principal | None
    ) -> tuple[str, SessionCookies | None]:
        payload = await self.consume_state(provider, state, browser)
        adapter = self.provider(provider)
        tokens = await adapter.exchange_code(code, payload.verifier)
        identity = await adapter.fetch_identity(tokens, payload.nonce)
        async with self.resources.database.transaction() as session:
            repository = AuthRepository(session)
            users = UsersService(session)
            existing = await repository.identity(provider, identity.subject)
            if payload.intent == "link":
                if (
                    principal is None
                    or principal.user_id != payload.user_id
                    or principal.session_id != payload.family_id
                ):
                    raise UnauthorizedError(code="unauthenticated")
                user = await self.auth.principal_user(session, principal)
                if existing and existing.user_id != user.id:
                    raise ConflictError(code="oauth_already_linked")
            elif existing:
                user = await users.get(existing.user_id, lock=True)
            else:
                user = await self.resolve_user(users, identity, session)
                await assign_default_role(session, user.id)
            self.auth.ensure_active(user)
            if existing is None:
                await repository.link(
                    OAuthIdentity(
                        id=new_id(),
                        user_id=user.id,
                        provider=provider,
                        subject=identity.subject,
                        email=identity.email,
                        email_verified=identity.email_verified,
                        last_login_at=self.resources.clock.now(),
                    )
                )
                self.resources.events.publish_after_commit(
                    session, OAuthIdentityLinked(user_id=user.id, provider=provider)
                )
                await self.auth.notice(session, user.id, "oauth_linked")
            else:
                existing.last_login_at = self.resources.clock.now()
            await self.auth.audit(session, "oauth.linked" if payload.intent == "link" else "oauth.succeeded", user.id)
            cookies: SessionCookies | None = None
            if payload.intent == "login":
                _, cookies = await self.auth.new_session(session, user)
        return self.resources.settings.auth.web_origin + payload.next_path, cookies

    async def resolve_user(self, users: UsersService, identity: ProviderIdentity, session: AsyncSession) -> User:
        if not identity.email or not identity.email_verified:
            raise UnauthorizedError(code="oauth_verified_email_required")
        identifier = normalize_identifier(identity.email)
        contact = await users.find_contact(identifier)
        if contact:
            return await users.get(contact.user_id, lock=True)
        user = await users.create_verified(identity.name, identifier, self.resources.clock.now())
        self.resources.events.publish_after_commit(session, UserRegistered(user_id=user.id))
        self.resources.events.publish_after_commit(session, ContactVerified(user_id=user.id))
        return user

    async def unlink(self, principal: Principal, provider: ProviderName) -> None:
        async with self.resources.database.transaction() as session:
            user = await self.auth.principal_user(session, principal)
            repository = AuthRepository(session)
            remaining = set(await repository.providers(user.id)) - {provider}
            contacts = await UsersService(session).contacts(user.id)
            if (
                not remaining
                and not await repository.credential(user.id)
                and not any(contact.verified_at for contact in contacts)
            ):
                raise ConflictError(code="last_sign_in_method")
            await repository.unlink(user.id, provider)
            await self.auth.audit(session, "oauth.unlinked", user.id)
