from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.modules.access.repository import AccessRepository


async def assign_default_role(session: AsyncSession, user_id: UUID) -> None:
    await AccessRepository(session).assign_default(user_id)


async def roles_for_user(session: AsyncSession, user_id: UUID) -> list[str]:
    return await AccessRepository(session).roles(user_id)
