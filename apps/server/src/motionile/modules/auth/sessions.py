from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.modules.auth.models import Session


async def active_session_count(session: AsyncSession, user_id: UUID, now: datetime) -> int:
    query = (
        select(func.count())
        .select_from(Session)
        .where(
            Session.user_id == user_id,
            Session.revoked_at.is_(None),
            Session.rotated_at.is_(None),
            Session.idle_expires_at > now,
            Session.absolute_expires_at > now,
        )
    )
    return int(await session.scalar(query) or 0)


async def session_families(session: AsyncSession, user_id: UUID) -> list[UUID]:
    return list(
        await session.scalars(
            select(Session.family_id).where(Session.user_id == user_id, Session.revoked_at.is_(None)).distinct()
        )
    )


async def revoke_user_sessions(session: AsyncSession, user_id: UUID, now: datetime, reason: str) -> None:
    await session.execute(
        update(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None))
        .values(revoked_at=now, revoke_reason=reason)
    )
