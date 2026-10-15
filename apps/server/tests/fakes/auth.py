import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.db import Database, run_after_commit
from motionile.core.errors import ConflictError, UnauthorizedError
from motionile.core.ids import new_id
from motionile.core.pagination import Cursor
from motionile.core.security.identifiers import Identifier
from motionile.modules.audit import AuditEvent
from motionile.modules.auth.models import Credential, OAuthIdentity, Session
from motionile.modules.auth.repository import AuthRepository
from motionile.modules.notifications import Notification
from motionile.modules.users import User, UserContact


@dataclass
class AuthState:
    users: dict[UUID, User] = field(default_factory=dict[UUID, User])
    contacts: list[UserContact] = field(default_factory=list[UserContact])
    credentials: dict[UUID, Credential] = field(default_factory=dict[UUID, Credential])
    sessions: dict[UUID, Session] = field(default_factory=dict[UUID, Session])
    identities: list[OAuthIdentity] = field(default_factory=list[OAuthIdentity])
    roles: dict[UUID, list[str]] = field(default_factory=dict[UUID, list[str]])
    notifications: list[Notification] = field(default_factory=list[Notification])
    audit: list[AuditEvent] = field(default_factory=list[AuditEvent])


class AuthDatabase(Database):
    def __init__(self, state: AuthState) -> None:
        self.state = state
        self.lock = asyncio.Lock()

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession]:
        async with self.lock, AsyncSession() as session:
            session.info["auth_state"] = self.state
            yield session
            await run_after_commit(session)


def state_of(session: AsyncSession) -> AuthState:
    state: AuthState = session.info["auth_state"]
    return state


class FakeUsersService:
    def __init__(self, session: AsyncSession) -> None:
        self.state = state_of(session)

    async def get(self, user_id: UUID, *, lock: bool = False) -> User:
        del lock
        user = self.state.users.get(user_id)
        if user is None or user.deleted_at:
            raise UnauthorizedError(code="unauthenticated")
        return user

    async def contacts(self, user_id: UUID) -> list[UserContact]:
        return [contact for contact in self.state.contacts if contact.user_id == user_id]

    async def find_contact(self, identifier: Identifier, *, verified_only: bool = True) -> UserContact | None:
        matches = [
            contact
            for contact in self.state.contacts
            if contact.value == identifier.value
            and self.state.users[contact.user_id].deleted_at is None
            and (contact.verified_at or not verified_only)
        ]
        return matches[-1] if matches else None

    async def create_pending(self, name: str, identifier: Identifier, now: datetime) -> User:
        user = User(id=new_id(), name=name, status="pending_verification", created_at=now, updated_at=now)
        self.state.users[user.id] = user
        self.state.contacts.append(
            UserContact(
                id=new_id(),
                user_id=user.id,
                kind=identifier.kind,
                value=identifier.value,
                is_primary=True,
                created_at=now,
                updated_at=now,
            )
        )
        return user

    async def create_verified(self, name: str, identifier: Identifier, now: datetime) -> User:
        user = await self.create_pending(name, identifier, now)
        return await self.activate(user.id, identifier, now)

    async def activate(self, user_id: UUID, identifier: Identifier, now: datetime) -> User:
        existing = await self.find_contact(identifier)
        if existing and existing.user_id != user_id:
            raise ConflictError(code="verification_conflict")
        user = await self.get(user_id)
        user.status = "active"
        for contact in await self.contacts(user_id):
            if contact.value == identifier.value:
                contact.verified_at = now
        return user

    async def mark_login(self, user_id: UUID, now: datetime) -> None:
        self.state.users[user_id].last_login_at = now


class FakeAuthRepository(AuthRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.state = state_of(session)

    async def credential(self, user_id: UUID) -> Credential | None:
        return self.state.credentials.get(user_id)

    async def set_password(self, user_id: UUID, encoded: str, now: datetime) -> None:
        self.state.credentials[user_id] = Credential(user_id=user_id, password_hash=encoded, password_updated_at=now)

    async def by_token(self, digest: bytes, *, lock: bool = False) -> Session | None:
        del lock
        return next((row for row in self.state.sessions.values() if row.token_hash == digest), None)

    async def lock_session(self, row: Session) -> None:
        if row.id not in self.state.sessions:
            raise LookupError

    async def insert_session(self, row: Session) -> None:
        self.state.sessions[row.id] = row

    async def active_sessions(self, user_id: UUID, now: datetime) -> list[Session]:
        return [
            row
            for row in self.state.sessions.values()
            if row.user_id == user_id
            and row.rotated_at is None
            and row.revoked_at is None
            and row.idle_expires_at > now
            and row.absolute_expires_at > now
        ]

    async def revocable_families(self, user_id: UUID) -> list[UUID]:
        return list(
            {row.family_id for row in self.state.sessions.values() if row.user_id == user_id and row.revoked_at is None}
        )

    async def session_page(
        self, user_id: UUID, now: datetime, cursor: Cursor | None, limit: int
    ) -> list[tuple[Session, Session]]:
        rows = [(row, self.state.sessions[row.family_id]) for row in await self.active_sessions(user_id, now)]
        if cursor:
            rows = [pair for pair in rows if (pair[1].created_at, pair[1].id) < (cursor.created_at, cursor.id)]
        return sorted(rows, key=lambda pair: (pair[1].created_at, pair[1].id), reverse=True)[: limit + 1]

    async def family(self, user_id: UUID, family_id: UUID) -> Session | None:
        row = self.state.sessions.get(family_id)
        return row if row and row.user_id == user_id else None

    async def revoke(self, user_id: UUID, family_id: UUID, reason: str, now: datetime) -> None:
        for row in self.state.sessions.values():
            if row.user_id == user_id and row.family_id == family_id and row.revoked_at is None:
                row.revoked_at = now
                row.revoke_reason = reason

    async def providers(self, user_id: UUID) -> list[str]:
        return sorted({row.provider for row in self.state.identities if row.user_id == user_id})

    async def identity(self, provider: str, subject: str) -> OAuthIdentity | None:
        return next((row for row in self.state.identities if row.provider == provider and row.subject == subject), None)

    async def link(self, identity: OAuthIdentity) -> None:
        self.state.identities.append(identity)

    async def unlink(self, user_id: UUID, provider: str) -> None:
        self.state.identities = [
            row for row in self.state.identities if row.user_id != user_id or row.provider != provider
        ]
