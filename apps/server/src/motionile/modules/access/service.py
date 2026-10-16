import json
from dataclasses import dataclass
from datetime import timedelta
from typing import cast
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.db import after_commit
from motionile.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from motionile.core.redis import RedisStore
from motionile.core.security.rbac import Principal
from motionile.modules.access.models import Role
from motionile.modules.access.permissions import PERMISSION_KEYS
from motionile.modules.access.repository import AccessRepository
from motionile.modules.access.schemas import RoleCreateRequest, RoleResponse, RoleUpdateRequest

ACCESS_CACHE_TTL = timedelta(minutes=5)
SUPER_ADMIN = "super_admin"


@dataclass(frozen=True)
class EffectiveAccess:
    roles: frozenset[str]
    permissions: frozenset[str]


def access_cache_key(redis: RedisStore, user_id: UUID) -> str:
    return redis.keys.key("access.effective", user_id)


async def invalidate_user_access(redis: RedisStore, user_id: UUID) -> None:
    await redis.delete(access_cache_key(redis, user_id))


def invalidate_user_access_after_commit(session: AsyncSession, redis: RedisStore, user_id: UUID) -> None:
    async def invalidate() -> None:
        await invalidate_user_access(redis, user_id)

    after_commit(session, invalidate)


async def resolve_access(
    session: AsyncSession, redis: RedisStore, user_id: UUID, *, use_cache: bool = True
) -> EffectiveAccess:
    key = access_cache_key(redis, user_id)
    cached = await redis.get(key) if use_cache else None
    if cached is not None:
        value = cast("object", json.loads(cached))
        if isinstance(value, dict):
            payload = cast("dict[str, object]", value)
            roles = payload.get("roles")
            permissions = payload.get("permissions")
            role_values = cast("list[object]", roles) if isinstance(roles, list) else None
            permission_values = cast("list[object]", permissions) if isinstance(permissions, list) else None
            if (
                role_values is not None
                and all(isinstance(role, str) for role in role_values)
                and permission_values is not None
                and all(isinstance(permission, str) for permission in permission_values)
            ):
                return EffectiveAccess(
                    frozenset(cast("list[str]", role_values)),
                    frozenset(cast("list[str]", permission_values)),
                )
    roles, permissions = await AccessRepository(session).effective_access(user_id)
    result = EffectiveAccess(frozenset(roles), frozenset(permissions))
    await redis.set(
        key,
        json.dumps({"roles": sorted(result.roles), "permissions": sorted(result.permissions)}),
        ttl=ACCESS_CACHE_TTL,
    )
    return result


async def assign_default_role(session: AsyncSession, user_id: UUID) -> None:
    await AccessRepository(session).assign_default(user_id)


async def roles_for_user(session: AsyncSession, user_id: UUID) -> list[str]:
    return await AccessRepository(session).roles(user_id)


async def grant_role_by_key(
    session: AsyncSession, redis: RedisStore, user_id: UUID, role_key: str, granted_by: UUID | None = None
) -> Role:
    repository = AccessRepository(session)
    role = await repository.role_by_key(role_key)
    if role is None:
        raise NotFoundError(code="role_not_found")
    await repository.assign_role(user_id, role.id, granted_by)
    invalidate_user_access_after_commit(session, redis, user_id)
    return role


class AccessService:
    def __init__(self, session: AsyncSession, redis: RedisStore) -> None:
        self.session = session
        self.redis = redis
        self.repository = AccessRepository(session)

    async def effective(self, user_id: UUID) -> EffectiveAccess:
        return await resolve_access(self.session, self.redis, user_id)

    async def roles(self) -> list[RoleResponse]:
        result: list[RoleResponse] = []
        for role in await self.repository.list_roles():
            result.append(
                RoleResponse(
                    id=role.id,
                    key=role.key,
                    name=role.name,
                    description=role.description,
                    is_system=role.is_system,
                    permissions=await self.repository.permission_keys(role.id),
                    user_count=await self.repository.role_user_count(role.id),
                    created_at=role.created_at,
                    updated_at=role.updated_at,
                )
            )
        return result

    async def create_role(self, actor: Principal, body: RoleCreateRequest) -> RoleResponse:
        permissions = self.validated_permissions(body.permissions)
        await self.ensure_actor_can_grant(actor, permissions)
        try:
            role = await self.repository.create_role(body.key, body.name, body.description)
            await self.repository.replace_permissions(role.id, permissions)
        except IntegrityError as error:
            raise ConflictError(code="role_key_exists") from error
        return self._response(role, permissions)

    async def update_role(self, actor: Principal, role_id: UUID, body: RoleUpdateRequest) -> RoleResponse:
        role = await self.repository.role(role_id, lock=True)
        if role is None:
            raise NotFoundError(code="role_not_found")
        permissions = set(await self.repository.permission_keys(role.id))
        if body.permissions is not None:
            permissions = self.validated_permissions(body.permissions)
            await self.ensure_actor_can_grant(actor, permissions)
            affected = await self.repository.users_with_role(role.id)
            await self.repository.replace_permissions(role.id, permissions)
            for user_id in affected:
                invalidate_user_access_after_commit(self.session, self.redis, user_id)
        if body.name is not None:
            role.name = body.name
        if body.description is not None:
            role.description = body.description
        await self.session.flush()
        return self._response(role, permissions, await self.repository.role_user_count(role.id))

    async def delete_role(self, role_id: UUID) -> None:
        role = await self.repository.role(role_id, lock=True)
        if role is None:
            raise NotFoundError(code="role_not_found")
        if role.is_system:
            raise ConflictError(code="system_role_immutable")
        if await self.repository.role_user_count(role_id):
            raise ConflictError(code="role_in_use")
        await self.repository.delete_role(role)

    async def assign(self, actor: Principal, user_id: UUID, role_id: UUID) -> None:
        role = await self.repository.role(role_id)
        if role is None:
            raise NotFoundError(code="role_not_found")
        await self.ensure_actor_can_grant(actor, set(await self.repository.permission_keys(role.id)))
        await self.repository.assign_role(user_id, role_id, actor.user_id)
        invalidate_user_access_after_commit(self.session, self.redis, user_id)

    async def remove(self, actor: Principal, user_id: UUID, role_id: UUID) -> None:
        role = await self.repository.role(role_id, lock=True)
        if role is None:
            raise NotFoundError(code="role_not_found")
        if role.key == SUPER_ADMIN:
            if actor.user_id == user_id:
                raise ConflictError(code="self_super_admin_removal")
            if await self.repository.count_role_key(SUPER_ADMIN) <= 1:
                raise ConflictError(code="last_super_admin")
        await self.repository.remove_role(user_id, role_id)
        invalidate_user_access_after_commit(self.session, self.redis, user_id)

    def validated_permissions(self, permissions: list[str]) -> set[str]:
        result = set(permissions)
        if len(result) != len(permissions) or not result.issubset(PERMISSION_KEYS):
            raise ValidationAppError(code="invalid_permissions")
        return result

    async def ensure_actor_can_grant(self, actor: Principal, permissions: set[str]) -> None:
        if actor.user_id is None:
            raise ForbiddenError(code="permission_denied")
        access = await self.effective(actor.user_id)
        if SUPER_ADMIN not in access.roles and not permissions.issubset(access.permissions):
            raise ForbiddenError(code="permission_escalation")

    def _response(self, role: Role, permissions: set[str], user_count: int = 0) -> RoleResponse:
        return RoleResponse(
            id=role.id,
            key=role.key,
            name=role.name,
            description=role.description,
            is_system=role.is_system,
            permissions=sorted(permissions),
            user_count=user_count,
            created_at=role.created_at,
            updated_at=role.updated_at,
        )
