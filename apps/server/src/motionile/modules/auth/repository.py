from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from motionile.core.pagination import Cursor
from motionile.modules.auth.models import Credential, OAuthIdentity, Session


class AuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def credential(self, user_id: UUID) -> Credential | None:
        return await self.session.get(Credential, user_id)

    async def set_password(self, user_id: UUID, encoded: str, now: datetime) -> None:
        credential = await self.credential(user_id)
        if credential is None:
            self.session.add(Credential(user_id=user_id, password_hash=encoded, password_updated_at=now))
        else:
            credential.password_hash = encoded
            credential.password_updated_at = now
        await self.session.flush()

    async def by_token(self, digest: bytes, *, lock: bool = False) -> Session | None:
        query = select(Session).where(Session.token_hash == digest)
        if lock:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def lock_session(self, row: Session) -> None:
        await self.session.refresh(row, with_for_update=True)

    async def insert_session(self, row: Session) -> None:
        self.session.add(row)
        await self.session.flush()

    async def active_sessions(self, user_id: UUID, now: datetime) -> list[Session]:
        query = (
            select(Session)
            .where(
                Session.user_id == user_id,
                Session.revoked_at.is_(None),
                Session.rotated_at.is_(None),
                Session.idle_expires_at > now,
                Session.absolute_expires_at > now,
            )
            .order_by(Session.created_at.desc(), Session.id.desc())
        )
        return list(await self.session.scalars(query))

    async def revocable_families(self, user_id: UUID) -> list[UUID]:
        query = select(Session.family_id).where(Session.user_id == user_id, Session.revoked_at.is_(None)).distinct()
        return list(await self.session.scalars(query))

    async def session_page(
        self, user_id: UUID, now: datetime, cursor: Cursor | None, limit: int
    ) -> list[tuple[Session, Session]]:
        root = aliased(Session)
        query = (
            select(Session, root)
            .join(root, root.id == Session.family_id)
            .where(
                Session.user_id == user_id,
                Session.revoked_at.is_(None),
                Session.rotated_at.is_(None),
                Session.idle_expires_at > now,
                Session.absolute_expires_at > now,
            )
        )
        if cursor is not None:
            query = query.where(tuple_(root.created_at, root.id) < tuple_(cursor.created_at, cursor.id))
        query = query.order_by(root.created_at.desc(), root.id.desc()).limit(limit + 1)
        rows = await self.session.execute(query)
        return [(row[0], row[1]) for row in rows]

    async def family(self, user_id: UUID, family_id: UUID) -> Session | None:
        return await self.session.scalar(select(Session).where(Session.user_id == user_id, Session.id == family_id))

    async def revoke(self, user_id: UUID, family_id: UUID, reason: str, now: datetime) -> None:
        await self.session.execute(
            update(Session)
            .where(Session.user_id == user_id, Session.family_id == family_id, Session.revoked_at.is_(None))
            .values(revoked_at=now, revoke_reason=reason)
        )

    async def providers(self, user_id: UUID) -> list[str]:
        return list(
            await self.session.scalars(
                select(OAuthIdentity.provider)
                .where(OAuthIdentity.user_id == user_id)
                .distinct()
                .order_by(OAuthIdentity.provider)
            )
        )

    async def identity(self, provider: str, subject: str) -> OAuthIdentity | None:
        return await self.session.scalar(
            select(OAuthIdentity).where(OAuthIdentity.provider == provider, OAuthIdentity.subject == subject)
        )

    async def link(self, identity: OAuthIdentity) -> None:
        self.session.add(identity)
        await self.session.flush()

    async def unlink(self, user_id: UUID, provider: str) -> None:
        await self.session.execute(
            delete(OAuthIdentity).where(OAuthIdentity.user_id == user_id, OAuthIdentity.provider == provider)
        )
