from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from motionile.core.dependencies import DatabaseDep, RedisStoreDep
from motionile.core.errors import problem_responses
from motionile.core.ratelimit.limiter import rate_limit
from motionile.modules.access.dependencies import RolesManageDep, RolesReadDep
from motionile.modules.access.permissions import PERMISSIONS
from motionile.modules.access.schemas import (
    AccessCatalogResponse,
    PermissionResponse,
    RoleCreateRequest,
    RoleResponse,
    RoleUpdateRequest,
)
from motionile.modules.access.service import AccessService
from motionile.modules.audit import ActorType, AuditEvent, context_from_request, record
from motionile.modules.auth import enforce_csrf

access_admin_router = APIRouter(
    prefix="/admin/roles",
    tags=["admin-roles"],
    dependencies=[Depends(enforce_csrf), Depends(rate_limit("api.default"))],
    responses=problem_responses(401, 403, 409, 422),
)


def access_resources(database: DatabaseDep, redis: RedisStoreDep) -> tuple[DatabaseDep, RedisStoreDep]:
    return database, redis


AccessResourcesDep = Annotated[tuple[DatabaseDep, RedisStoreDep], Depends(access_resources)]


@access_admin_router.get(
    "", response_model=AccessCatalogResponse, status_code=200, summary="List roles and permissions"
)
async def list_roles(request: Request, resources: AccessResourcesDep, principal: RolesReadDep) -> AccessCatalogResponse:
    database, redis = resources
    async with database.transaction() as session:
        service = AccessService(session, redis)
        result = AccessCatalogResponse(
            roles=await service.roles(),
            permissions=[PermissionResponse(key=item.key, description=item.description) for item in PERMISSIONS],
        )
        await record(
            session,
            AuditEvent(
                action="roles.listed",
                actor_type=ActorType.ADMIN,
                actor_user_id=principal.user_id,
                target_type="role",
            ),
            context_from_request(request),
        )
        return result


@access_admin_router.post("", response_model=RoleResponse, status_code=201, summary="Create a custom role")
async def create_role(
    body: RoleCreateRequest,
    request: Request,
    resources: AccessResourcesDep,
    principal: RolesManageDep,
) -> RoleResponse:
    database, redis = resources
    async with database.transaction() as session:
        role = await AccessService(session, redis).create_role(principal, body)
        await record(
            session,
            AuditEvent(
                action="roles.created",
                actor_type=ActorType.ADMIN,
                actor_user_id=principal.user_id,
                target_type="role",
                target_id=str(role.id),
                metadata={"key": role.key},
            ),
            context_from_request(request),
        )
        return role


@access_admin_router.patch(
    "/{role_id}", response_model=RoleResponse, status_code=200, summary="Update a role and its permissions"
)
async def update_role(
    role_id: UUID,
    body: RoleUpdateRequest,
    request: Request,
    resources: AccessResourcesDep,
    principal: RolesManageDep,
) -> RoleResponse:
    database, redis = resources
    async with database.transaction() as session:
        role = await AccessService(session, redis).update_role(principal, role_id, body)
        await record(
            session,
            AuditEvent(
                action="roles.updated",
                actor_type=ActorType.ADMIN,
                actor_user_id=principal.user_id,
                target_type="role",
                target_id=str(role_id),
                metadata={"permissions": role.permissions},
            ),
            context_from_request(request),
        )
        return role


@access_admin_router.delete(
    "/{role_id}", response_model=None, status_code=status.HTTP_204_NO_CONTENT, summary="Delete a custom role"
)
async def delete_role(
    role_id: UUID,
    request: Request,
    resources: AccessResourcesDep,
    principal: RolesManageDep,
) -> None:
    database, redis = resources
    async with database.transaction() as session:
        await AccessService(session, redis).delete_role(role_id)
        await record(
            session,
            AuditEvent(
                action="roles.deleted",
                actor_type=ActorType.ADMIN,
                actor_user_id=principal.user_id,
                target_type="role",
                target_id=str(role_id),
            ),
            context_from_request(request),
        )
