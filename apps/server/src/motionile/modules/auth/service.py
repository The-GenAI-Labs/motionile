from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.errors import ConflictError, ForbiddenError, NotFoundError, RateLimitedError, UnauthorizedError
from motionile.core.ids import new_id
from motionile.core.pagination import Cursor, build_page
from motionile.core.ratelimit.limiter import RateLimitIdentity
from motionile.core.security.cookies import SessionCookies
from motionile.core.security.identifiers import Identifier, normalize_identifier
from motionile.core.security.rbac import Principal, PrincipalKind
from motionile.core.security.tokens import random_token, token_hash
from motionile.modules.access import assign_default_role, resolve_access, roles_for_user
from motionile.modules.audit import ActorType, AuditContext, AuditEvent, record
from motionile.modules.auth.events import (
    ContactVerified,
    PasswordChanged,
    RefreshTokenReuseDetected,
    SessionFamilyRevoked,
    UserRegistered,
    UserSignedIn,
)
from motionile.modules.auth.exceptions import VerificationRequiredError
from motionile.modules.auth.models import Session
from motionile.modules.auth.otp import OtpPurpose
from motionile.modules.auth.repository import AuthRepository
from motionile.modules.auth.runtime import AuthRuntime
from motionile.modules.auth.schemas import (
    ChallengeResponse,
    ContactResponse,
    SessionListQuery,
    SessionResponse,
    SessionsResponse,
    SessionUser,
)
from motionile.modules.notifications import Notification, TemplateName, enqueue_notification
from motionile.modules.users import User, UsersService

MAX_TOKEN_LENGTH = 128

IDLE_LIFETIME = timedelta(days=7)
ABSOLUTE_LIFETIME = timedelta(days=60)
REFRESH_GRACE = timedelta(seconds=10)
LOCKOUT_THRESHOLD = 10
LOCKOUT_WINDOW = timedelta(hours=1)
LOCKOUT_DURATION = timedelta(minutes=15)


def device_label(user_agent: str | None) -> str:
    agent = user_agent or ""
    browser = next(
        (
            label
            for needle, label in (
                ("Edg/", "Edge"),
                ("Firefox/", "Firefox"),
                ("Chrome/", "Chrome"),
                ("Safari/", "Safari"),
            )
            if needle in agent
        ),
        "Unknown browser",
    )
    platform = next(
        (
            label
            for needle, label in (
                ("Android", "Android"),
                ("iPhone", "iOS"),
                ("Windows", "Windows"),
                ("Macintosh", "macOS"),
                ("Linux", "Linux"),
            )
            if needle in agent
        ),
        "Unknown device",
    )
    return f"{browser} on {platform}"


class AuthService:
    def __init__(self, runtime: AuthRuntime, context: AuditContext) -> None:
        self.runtime = runtime
        self.resources = runtime.resources
        self.context = context

    async def audit(self, session: AsyncSession, action: str, user_id: UUID | None = None) -> None:
        await record(
            session,
            AuditEvent(
                action=f"auth.{action}",
                actor_type=ActorType.USER if user_id else ActorType.SYSTEM,
                actor_user_id=user_id,
                target_type="user" if user_id else None,
                target_id=str(user_id) if user_id else None,
            ),
            self.context,
        )

    async def notice(self, session: AsyncSession, user_id: UUID, template: TemplateName) -> None:
        for contact in await UsersService(session).contacts(user_id):
            if contact.verified_at and contact.is_primary:
                identifier = normalize_identifier(contact.value)
                enqueue_notification(
                    self.resources,
                    session,
                    Notification(destination=identifier.value, channel=identifier.channel, template=template),
                )

    async def limit(self, policy: str, *, identifier: str | None = None, principal: Principal | None = None) -> None:
        limiter = self.resources.rate_limiter
        decision = await limiter.check(
            limiter.policy(policy),
            RateLimitIdentity(
                ip=str(self.context.ip) if self.context.ip else None,
                identifier=identifier,
                user_id=str(principal.user_id) if principal else None,
                session_id=str(principal.session_id) if principal else None,
            ),
        )
        if decision is not None and not decision.allowed:
            raise RateLimitedError(headers=decision.headers())

    async def challenge(
        self, session: AsyncSession, purpose: OtpPurpose, identifier: Identifier, user_id: UUID | None
    ) -> tuple[str, ChallengeResponse]:
        await self.limit("auth.otp.send", identifier=identifier.value)
        ticket, challenge, code = await self.runtime.otp.issue(purpose, identifier, user_id)
        if challenge.user_id is not None:
            enqueue_notification(
                self.resources,
                session,
                Notification(destination=identifier.value, channel=identifier.channel, template=purpose, code=code),
            )
        return ticket, ChallengeResponse(destination=identifier.masked, channel=identifier.channel)

    async def register(self, name: str, identifier: Identifier, password: str) -> tuple[str, ChallengeResponse]:
        await self.runtime.passwords.validate(password)
        encoded = await self.runtime.passwords.hash(password)
        async with self.resources.database.transaction() as session:
            users = UsersService(session)
            existing = await users.find_contact(identifier)
            user_id: UUID | None = None
            if existing is None:
                user = await users.create_pending(name, identifier, self.resources.clock.now())
                user_id = user.id
                await AuthRepository(session).set_password(user.id, encoded, self.resources.clock.now())
                self.resources.events.publish_after_commit(session, UserRegistered(user_id=user.id))
            else:
                enqueue_notification(
                    self.resources,
                    session,
                    Notification(destination=identifier.value, channel=identifier.channel, template="account_exists"),
                )
            result = await self.challenge(session, "verify_contact", identifier, user_id)
            await self.audit(session, "register.requested")
        return result

    async def session_user(self, session: AsyncSession, user: User) -> SessionUser:
        contacts = await UsersService(session).contacts(user.id)
        repository = AuthRepository(session)
        access = await resolve_access(session, self.resources.redis_store, user.id)
        return SessionUser(
            id=user.id,
            name=user.name,
            status=user.status,
            roles=sorted(access.roles),
            permissions=sorted(access.permissions),
            contacts=[
                ContactResponse(
                    kind=contact.kind,
                    destination=normalize_identifier(contact.value).masked,
                    verified=contact.verified_at is not None,
                    primary=contact.is_primary,
                )
                for contact in contacts
            ],
            has_password=await repository.credential(user.id) is not None,
            linked_providers=await repository.providers(user.id),
        )

    def ensure_active(self, user: User) -> None:
        if user.status == "suspended":
            raise ForbiddenError(code="account_suspended")
        if user.status != "active":
            raise UnauthorizedError(code="invalid_credentials")

    async def new_session(self, session: AsyncSession, user: User) -> tuple[SessionUser, SessionCookies]:
        self.ensure_active(user)
        now = self.resources.clock.now()
        family_id = new_id()
        refresh = random_token()
        repository = AuthRepository(session)
        label = device_label(self.context.user_agent)
        known = await repository.active_sessions(user.id, now)
        row = Session(
            id=family_id,
            family_id=family_id,
            user_id=user.id,
            token_hash=token_hash(refresh),
            idle_expires_at=now + IDLE_LIFETIME,
            absolute_expires_at=now + ABSOLUTE_LIFETIME,
            ip=str(self.context.ip) if self.context.ip else None,
            user_agent=self.context.user_agent,
            device_label=label,
            last_used_at=now,
            created_at=now,
            updated_at=now,
        )
        await repository.insert_session(row)
        await UsersService(session).mark_login(user.id, now)
        if not any(item.device_label == label for item in known):
            await self.notice(session, user.id, "new_sign_in")
        self.resources.events.publish_after_commit(session, UserSignedIn(user_id=user.id, family_id=family_id))
        await self.audit(session, "login.succeeded", user.id)
        view = await self.session_user(session, user)
        return view, self.cookies(row, refresh, view.roles)

    def cookies(self, row: Session, refresh: str, roles: list[str]) -> SessionCookies:
        now = self.resources.clock.now()
        return SessionCookies(
            access=self.runtime.tokens.issue(row.user_id, row.family_id, roles),
            refresh=refresh,
            csrf=self.runtime.csrf.issue(row.family_id),
            expires_at=now + timedelta(seconds=self.resources.settings.auth.access_seconds),
            access_max_age=self.resources.settings.auth.access_seconds,
            refresh_max_age=max(0, int((row.idle_expires_at - now).total_seconds())),
        )

    async def verify_contact(self, ticket: str | None, code: str) -> tuple[SessionUser, SessionCookies]:
        challenge = await self.runtime.otp.verify(ticket, "verify_contact", code)
        if challenge.user_id is None:
            raise UnauthorizedError(code="invalid_challenge")
        async with self.resources.database.transaction() as session:
            user = await UsersService(session).activate(
                challenge.user_id, challenge.identifier, self.resources.clock.now()
            )
            await assign_default_role(session, user.id)
            self.resources.events.publish_after_commit(session, ContactVerified(user_id=user.id))
            await self.audit(session, "contact.verified", user.id)
            return await self.new_session(session, user)

    async def password_login(self, identifier: Identifier, password: str) -> tuple[SessionUser, SessionCookies]:
        store = self.resources.redis_store
        subject = token_hash(identifier.value).hex()
        failures = store.keys.key("auth.failures", subject)
        lock = store.keys.key("auth.lockout", subject)
        error: UnauthorizedError | ForbiddenError | None = None
        result: tuple[SessionUser, SessionCookies] | None = None
        async with self.resources.database.transaction() as session:
            users = UsersService(session)
            contact = await users.find_contact(identifier, verified_only=False)
            user = await users.get(contact.user_id, lock=True) if contact else None
            repository = AuthRepository(session)
            credential = await repository.credential(user.id) if user else None
            valid = await self.runtime.passwords.verify(password, credential.password_hash if credential else None)
            locked = await store.get(lock) is not None
            if not valid or locked or user is None or contact is None:
                count = 0 if locked else await store.increment(failures, ttl=LOCKOUT_WINDOW)
                if count >= LOCKOUT_THRESHOLD and not locked:
                    await store.set(lock, "1", ttl=LOCKOUT_DURATION)
                    await store.delete(failures)
                    if user:
                        await self.notice(session, user.id, "password_lockout")
                await self.audit(session, "login.failed")
                error = UnauthorizedError(code="invalid_credentials")
            elif user.status == "suspended":
                error = ForbiddenError(code="account_suspended")
                await self.audit(session, "login.denied", user.id)
            elif contact.verified_at is None:
                verification_ticket, details = await self.challenge(session, "verify_contact", identifier, user.id)
                error = VerificationRequiredError(verification_ticket, details)
                await self.audit(session, "verification.requested", user.id)
            else:
                await store.delete(failures)
                if credential and self.runtime.passwords.needs_rehash(credential.password_hash):
                    await repository.set_password(
                        user.id, await self.runtime.passwords.hash(password), self.resources.clock.now()
                    )
                result = await self.new_session(session, user)
        if error:
            raise error
        if result is None:
            raise UnauthorizedError(code="invalid_credentials")
        return result

    async def request_otp(self, identifier: Identifier, purpose: OtpPurpose) -> tuple[str, ChallengeResponse]:
        async with self.resources.database.transaction() as session:
            users = UsersService(session)
            contact = await users.find_contact(identifier)
            user = await users.get(contact.user_id) if contact else None
            user_id = user.id if user and user.status == "active" else None
            result = await self.challenge(session, purpose, identifier, user_id)
            await self.audit(session, f"{purpose}.requested")
        return result

    async def resend(self, value: str | None) -> tuple[str, ChallengeResponse]:
        ticket = await self.runtime.otp.ticket(value)
        await self.limit("auth.otp.send", identifier=ticket.destination)
        new_ticket, challenge, code = await self.runtime.otp.issue(ticket.purpose, ticket.identifier, ticket.user_id)
        await self.resources.redis_store.delete(self.runtime.otp.challenge_key(ticket.challenge_id))
        if value:
            await self.resources.redis_store.delete(self.runtime.otp.ticket_key(value))
        async with self.resources.database.transaction() as session:
            if challenge.user_id:
                enqueue_notification(
                    self.resources,
                    session,
                    Notification(
                        destination=challenge.destination,
                        channel=challenge.identifier.channel,
                        template=challenge.purpose,
                        code=code,
                    ),
                )
            await self.audit(session, "otp.resent")
        return new_ticket, ChallengeResponse(
            destination=challenge.identifier.masked, channel=challenge.identifier.channel
        )

    async def otp_login(self, ticket: str | None, code: str) -> tuple[SessionUser, SessionCookies]:
        challenge = await self.runtime.otp.verify(ticket, "login", code)
        if challenge.user_id is None:
            raise UnauthorizedError(code="invalid_challenge")
        async with self.resources.database.transaction() as session:
            user = await UsersService(session).get(challenge.user_id, lock=True)
            self.ensure_active(user)
            return await self.new_session(session, user)

    async def revoke_family(self, session: AsyncSession, user_id: UUID, family_id: UUID, reason: str) -> None:
        await AuthRepository(session).revoke(user_id, family_id, reason, self.resources.clock.now())
        await self.runtime.tokens.revoke(family_id)
        self.resources.events.publish_after_commit(
            session, SessionFamilyRevoked(user_id=user_id, family_id=family_id, reason=reason)
        )
        await self.audit(session, "session.revoked", user_id)

    async def revoke_all(self, session: AsyncSession, user_id: UUID, reason: str, keep: UUID | None = None) -> None:
        for family_id in await AuthRepository(session).revocable_families(user_id):
            if family_id != keep:
                await self.revoke_family(session, user_id, family_id, reason)

    async def refresh(self, token: str | None, csrf_cookie: str | None, csrf_header: str | None) -> SessionCookies:
        if not token or len(token) > MAX_TOKEN_LENGTH:
            raise UnauthorizedError(code="unauthenticated")
        error: UnauthorizedError | None = None
        result: SessionCookies | None = None
        async with self.resources.database.transaction() as session:
            repository = AuthRepository(session)
            row = await repository.by_token(token_hash(token))
            if row is None:
                raise UnauthorizedError(code="unauthenticated")
            user = await UsersService(session).get(row.user_id, lock=True)
            await repository.lock_session(row)
            await self.limit(
                "auth.refresh",
                principal=Principal(kind=PrincipalKind.USER, user_id=row.user_id, session_id=row.family_id),
            )
            self.runtime.csrf.verify(row.family_id, csrf_cookie, csrf_header)
            self.ensure_active(user)
            now = self.resources.clock.now()
            if row.revoked_at is not None:
                error = UnauthorizedError(code="unauthenticated")
            elif row.rotated_at is not None:
                if now - row.rotated_at <= REFRESH_GRACE:
                    error = UnauthorizedError(code="refresh_conflict")
                else:
                    await self.revoke_family(session, user.id, row.family_id, "reuse_detected")
                    await self.notice(session, user.id, "refresh_reuse")
                    self.resources.events.publish_after_commit(
                        session, RefreshTokenReuseDetected(user_id=user.id, family_id=row.family_id)
                    )
                    error = UnauthorizedError(code="refresh_reused")
            elif row.idle_expires_at <= now or row.absolute_expires_at <= now:
                error = UnauthorizedError(code="session_expired")
            else:
                refresh = random_token()
                successor = Session(
                    id=new_id(),
                    family_id=row.family_id,
                    user_id=row.user_id,
                    token_hash=token_hash(refresh),
                    parent_id=row.id,
                    idle_expires_at=min(now + IDLE_LIFETIME, row.absolute_expires_at),
                    absolute_expires_at=row.absolute_expires_at,
                    ip=str(self.context.ip) if self.context.ip else None,
                    user_agent=self.context.user_agent,
                    device_label=device_label(self.context.user_agent),
                    last_used_at=now,
                    created_at=now,
                    updated_at=now,
                )
                row.rotated_at = now
                row.last_used_at = now
                await repository.insert_session(successor)
                result = self.cookies(successor, refresh, await roles_for_user(session, row.user_id))
            await self.audit(session, "refresh.failed" if error else "refresh.succeeded", user.id)
        if error:
            raise error
        if result is None:
            raise UnauthorizedError(code="unauthenticated")
        return result

    async def principal_user(self, session: AsyncSession, principal: Principal) -> User:
        if principal.user_id is None or principal.session_id is None:
            raise UnauthorizedError(code="unauthenticated")
        user = await UsersService(session).get(principal.user_id, lock=True)
        self.ensure_active(user)
        if await self.resources.redis_store.get(
            self.resources.redis_store.keys.key("auth.revoked", principal.session_id)
        ):
            raise UnauthorizedError(code="unauthenticated")
        return user

    async def me(self, principal: Principal) -> SessionUser:
        async with self.resources.database.transaction() as session:
            user = await self.principal_user(session, principal)
            await self.audit(session, "me.read", user.id)
            return await self.session_user(session, user)

    async def sessions(self, principal: Principal, query: SessionListQuery | None = None) -> SessionsResponse:
        query = query or SessionListQuery()
        codec = self.resources.cursor_codec
        cursor = codec.decode(query.cursor) if query.cursor else None
        async with self.resources.database.transaction() as session:
            user = await self.principal_user(session, principal)
            rows = await AuthRepository(session).session_page(user.id, self.resources.clock.now(), cursor, query.limit)
            items, next_cursor = build_page(
                rows, limit=query.limit, codec=codec, key=lambda pair: Cursor(pair[1].created_at, pair[1].id)
            )
            await self.audit(session, "sessions.listed", user.id)
            return SessionsResponse(
                items=[
                    SessionResponse(
                        id=row.family_id,
                        device_label=row.device_label,
                        ip=str(row.ip) if row.ip else None,
                        created_at=root.created_at,
                        last_used_at=row.last_used_at,
                        current=row.family_id == principal.session_id,
                    )
                    for row, root in items
                ],
                next_cursor=next_cursor,
            )

    async def logout(self, principal: Principal, *, everywhere: bool = False, family_id: UUID | None = None) -> None:
        async with self.resources.database.transaction() as session:
            user = await self.principal_user(session, principal)
            if everywhere:
                await self.revoke_all(session, user.id, "logout_all")
            else:
                target = family_id or principal.session_id
                if target is None or await AuthRepository(session).family(user.id, target) is None:
                    raise NotFoundError
                await self.revoke_family(session, user.id, target, "logout")

    async def password_changed(
        self, session: AsyncSession, user_id: UUID, encoded: str, keep: UUID | None = None
    ) -> None:
        await AuthRepository(session).set_password(user_id, encoded, self.resources.clock.now())
        await self.revoke_all(session, user_id, "password_changed", keep)
        await self.notice(session, user_id, "password_changed")
        self.resources.events.publish_after_commit(session, PasswordChanged(user_id=user_id))
        await self.audit(session, "password.changed", user_id)

    async def reset_password(
        self, ticket: str | None, code: str, password: str, principal: Principal | None = None
    ) -> None:
        await self.runtime.passwords.validate(password)
        purpose: OtpPurpose = "set_password" if principal else "password_reset"
        challenge = await self.runtime.otp.verify(ticket, purpose, code)
        if challenge.user_id is None or (principal and principal.user_id != challenge.user_id):
            raise UnauthorizedError(code="invalid_challenge")
        encoded = await self.runtime.passwords.hash(password)
        async with self.resources.database.transaction() as session:
            user = (
                await self.principal_user(session, principal)
                if principal
                else await UsersService(session).get(challenge.user_id, lock=True)
            )
            self.ensure_active(user)
            if principal and await AuthRepository(session).credential(user.id):
                raise ConflictError(code="password_already_set")
            await self.password_changed(session, user.id, encoded, principal.session_id if principal else None)

    async def change_password(self, principal: Principal, current: str, password: str) -> None:
        await self.runtime.passwords.validate(password)
        encoded = await self.runtime.passwords.hash(password)
        async with self.resources.database.transaction() as session:
            user = await self.principal_user(session, principal)
            credential = await AuthRepository(session).credential(user.id)
            if not await self.runtime.passwords.verify(current, credential.password_hash if credential else None):
                raise UnauthorizedError(code="invalid_credentials")
            await self.password_changed(session, user.id, encoded, principal.session_id)

    async def request_password(self, principal: Principal) -> tuple[str, ChallengeResponse]:
        async with self.resources.database.transaction() as session:
            user = await self.principal_user(session, principal)
            if await AuthRepository(session).credential(user.id):
                raise ConflictError(code="password_already_set")
            contacts = await UsersService(session).contacts(user.id)
            contact = next((item for item in contacts if item.is_primary and item.verified_at), None)
            if contact is None:
                raise ConflictError(code="verified_contact_required")
            result = await self.challenge(session, "set_password", normalize_identifier(contact.value), user.id)
            await self.audit(session, "password_set.requested", user.id)
        return result
