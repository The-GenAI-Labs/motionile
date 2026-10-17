from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.ids import new_id
from motionile.modules.access.models import Permission, Role, RolePermission, UserRole


class AccessRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def roles(self, user_id: UUID) -> list[str]:
        query = select(Role.key).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
        return list(await self.session.scalars(query.order_by(Role.key)))

    async def effective_access(self, user_id: UUID) -> tuple[list[str], list[str]]:
        roles = await self.roles(user_id)
        if "super_admin" in roles:
            permissions = list(await self.session.scalars(select(Permission.key).order_by(Permission.key)))
            return roles, permissions
        query = (
            select(Permission.key)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(Role, Role.id == RolePermission.role_id)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
            .distinct()
            .order_by(Permission.key)
        )
        return roles, list(await self.session.scalars(query))

    async def role(self, role_id: UUID, *, lock: bool = False) -> Role | None:
        query = select(Role).where(Role.id == role_id)
        if lock:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def role_by_key(self, key: str, *, lock: bool = False) -> Role | None:
        query = select(Role).where(Role.key == key)
        if lock:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def list_roles(self) -> list[Role]:
        return list(await self.session.scalars(select(Role).order_by(Role.is_system.desc(), Role.key)))

    async def permission_keys(self, role_id: UUID) -> list[str]:
        query = (
            select(Permission.key)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_id)
            .order_by(Permission.key)
        )
        return list(await self.session.scalars(query))

    async def permissions(self) -> list[Permission]:
        return list(await self.session.scalars(select(Permission).order_by(Permission.key)))

    async def users_with_role(self, role_id: UUID) -> list[UUID]:
        return list(await self.session.scalars(select(UserRole.user_id).where(UserRole.role_id == role_id)))

    async def role_user_count(self, role_id: UUID) -> int:
        return int(
            await self.session.scalar(select(func.count()).select_from(UserRole).where(UserRole.role_id == role_id))
            or 0
        )

    async def create_role(self, key: str, name: str, description: str | None) -> Role:
        role = Role(id=new_id(), key=key, name=name, description=description, is_system=False)
        self.session.add(role)
        await self.session.flush()
        return role

    async def replace_permissions(self, role_id: UUID, keys: set[str]) -> None:
        await self.session.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
        permission_ids = list(await self.session.scalars(select(Permission.id).where(Permission.key.in_(keys))))
        if len(permission_ids) != len(keys):
            raise LookupError
        self.session.add_all(
            [RolePermission(role_id=role_id, permission_id=permission_id) for permission_id in permission_ids]
        )
        await self.session.flush()

    async def assign_role(self, user_id: UUID, role_id: UUID, granted_by: UUID | None) -> None:
        await self.session.execute(
            insert(UserRole).values(user_id=user_id, role_id=role_id, granted_by=granted_by).on_conflict_do_nothing()
        )

    async def remove_role(self, user_id: UUID, role_id: UUID) -> None:
        await self.session.execute(delete(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role_id))

    async def delete_role(self, role: Role) -> None:
        await self.session.delete(role)

    async def count_role_key(self, key: str) -> int:
        query = select(func.count()).select_from(UserRole).join(Role).where(Role.key == key)
        return int(await self.session.scalar(query) or 0)

    async def assign_default(self, user_id: UUID) -> None:
        role_id = (await self.session.execute(select(Role.id).where(Role.key == "user"))).scalar_one()
        await self.session.execute(insert(UserRole).values(user_id=user_id, role_id=role_id).on_conflict_do_nothing())
