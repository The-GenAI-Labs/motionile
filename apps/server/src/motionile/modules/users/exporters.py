from typing import Any, Protocol, cast
from uuid import UUID

from sqlalchemy import Table, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.modules.audit import AuditLogEntry
from motionile.modules.auth import Session
from motionile.modules.users.exports import registry
from motionile.modules.users.models import User, UserContact, UserPreference


class TableBacked(Protocol):
    __table__: Table


def serialize(row: object) -> dict[str, Any]:
    table = cast("TableBacked", row).__table__
    return {column.name: getattr(row, column.key) for column in table.columns}


async def export_profile(session: AsyncSession, user_id: UUID) -> object:
    row = await session.get(User, user_id)
    return serialize(row) if row is not None else None


async def export_contacts(session: AsyncSession, user_id: UUID) -> object:
    rows = await session.scalars(select(UserContact).where(UserContact.user_id == user_id))
    return [serialize(row) for row in rows]


async def export_preferences(session: AsyncSession, user_id: UUID) -> object:
    row = await session.get(UserPreference, user_id)
    return serialize(row) if row is not None else None


async def export_sessions(session: AsyncSession, user_id: UUID) -> object:
    rows = await session.scalars(select(Session).where(Session.user_id == user_id))
    result = [serialize(row) for row in rows]
    for item in result:
        item.pop("token_hash", None)
    return result


async def export_audit(session: AsyncSession, user_id: UUID) -> object:
    rows = await session.scalars(
        select(AuditLogEntry).where(
            or_(AuditLogEntry.actor_user_id == user_id, AuditLogEntry.target_id == str(user_id))
        )
    )
    return [serialize(row) for row in rows]


registry.register("profile", export_profile)
registry.register("contacts", export_contacts)
registry.register("preferences", export_preferences)
registry.register("sessions", export_sessions)
registry.register("audit", export_audit)
