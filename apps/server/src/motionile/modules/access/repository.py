from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.modules.access.models import Role, UserRole


class AccessRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def roles(self, user_id: UUID) -> list[str]:
        query = select(Role.key).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
        return list(await self.session.scalars(query.order_by(Role.key)))

    async def assign_default(self, user_id: UUID) -> None:
        role_id = (await self.session.execute(select(Role.id).where(Role.key == "user"))).scalar_one()
        await self.session.execute(insert(UserRole).values(user_id=user_id, role_id=role_id).on_conflict_do_nothing())
