from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from motionile.core.dependencies import DatabaseDep, RedisStoreDep
from motionile.core.errors import ForbiddenError, NotFoundError, problem_responses
from motionile.core.ratelimit.limiter import rate_limit
from motionile.modules.access import FlagsManageDep, SettingsManageDep, SettingsReadDep
from motionile.modules.audit import ActorType, AuditEvent, context_from_request, record
from motionile.modules.auth import OptionalPrincipalDep, enforce_csrf
from motionile.modules.platform.schemas import (
    EvaluatedFlagsResponse,
    FeatureFlagDeleteRequest,
    FeatureFlagResponse,
    FeatureFlagUpdateRequest,
    FeatureFlagWriteRequest,
    PublicSettingsResponse,
    SettingResponse,
    SettingUpdateRequest,
)
from motionile.modules.platform.service import PlatformService

platform_router = APIRouter(
    tags=["platform"],
    dependencies=[Depends(enforce_csrf), Depends(rate_limit("api.default"))],
    responses=problem_responses(401, 403, 409, 422),
)
platform_admin_router = APIRouter(prefix="/admin", tags=["admin-platform"])


def platform_resources(database: DatabaseDep, redis: RedisStoreDep) -> tuple[DatabaseDep, RedisStoreDep]:
    return database, redis


PlatformResourcesDep = Annotated[tuple[DatabaseDep, RedisStoreDep], Depends(platform_resources)]


def actor_id(principal: SettingsManageDep | FlagsManageDep) -> UUID:
    if principal.user_id is None:
        raise ForbiddenError(code="permission_denied")
    return principal.user_id


@platform_router.get(
    "/settings/public", response_model=PublicSettingsResponse, status_code=200, summary="List public settings"
)
async def public_settings(resources: PlatformResourcesDep) -> PublicSettingsResponse:
    database, redis = resources
    async with database.transaction() as session:
        return await PlatformService(session, redis).public_settings()


@platform_router.get("/flags", response_model=EvaluatedFlagsResponse, status_code=200, summary="Evaluate feature flags")
async def evaluated_flags(resources: PlatformResourcesDep, principal: OptionalPrincipalDep) -> EvaluatedFlagsResponse:
    database, redis = resources
    async with database.transaction() as session:
        return await PlatformService(session, redis).evaluated_flags(principal)


@platform_admin_router.get(
    "/settings", response_model=list[SettingResponse], status_code=200, summary="List system settings"
)
async def list_settings(
    request: Request, resources: PlatformResourcesDep, principal: SettingsReadDep
) -> list[SettingResponse]:
    database, redis = resources
    async with database.transaction() as session:
        result = await PlatformService(session, redis).settings()
        await record(
            session,
            AuditEvent(
                action="settings.listed",
                actor_type=ActorType.ADMIN,
                actor_user_id=actor_id(principal),
                target_type="setting",
            ),
            context_from_request(request),
        )
        return result


@platform_admin_router.get(
    "/settings/{key}", response_model=SettingResponse, status_code=200, summary="Get a system setting"
)
async def get_setting(
    key: str, request: Request, resources: PlatformResourcesDep, principal: SettingsReadDep
) -> SettingResponse:
    database, redis = resources
    async with database.transaction() as session:
        settings = await PlatformService(session, redis).settings()
        match = next((item for item in settings if item.key == key), None)
        if match is None:
            raise NotFoundError(code="setting_not_found")
        await record(
            session,
            AuditEvent(
                action="settings.read",
                actor_type=ActorType.ADMIN,
                actor_user_id=actor_id(principal),
                target_type="setting",
                target_id=key,
            ),
            context_from_request(request),
        )
        return match


@platform_admin_router.put(
    "/settings/{key}", response_model=SettingResponse, status_code=200, summary="Update a system setting"
)
async def update_setting(
    key: str,
    body: SettingUpdateRequest,
    request: Request,
    resources: PlatformResourcesDep,
    principal: SettingsManageDep,
) -> SettingResponse:
    database, redis = resources
    current_actor_id = actor_id(principal)
    async with database.transaction() as session:
        result = await PlatformService(session, redis).update_setting(key, body.value, body.version, current_actor_id)
        await record(
            session,
            AuditEvent(
                action="settings.updated",
                actor_type=ActorType.ADMIN,
                actor_user_id=current_actor_id,
                target_type="setting",
                target_id=key,
                metadata={"version": result.version},
            ),
            context_from_request(request),
        )
        return result


@platform_admin_router.get(
    "/flags", response_model=list[FeatureFlagResponse], status_code=200, summary="List feature flags"
)
async def list_flags(
    request: Request, resources: PlatformResourcesDep, principal: FlagsManageDep
) -> list[FeatureFlagResponse]:
    database, redis = resources
    async with database.transaction() as session:
        result = await PlatformService(session, redis).flags()
        await record(
            session,
            AuditEvent(
                action="flags.listed",
                actor_type=ActorType.ADMIN,
                actor_user_id=actor_id(principal),
                target_type="feature_flag",
            ),
            context_from_request(request),
        )
        return result


@platform_admin_router.post(
    "/flags", response_model=FeatureFlagResponse, status_code=201, summary="Create a feature flag"
)
async def create_flag(
    body: FeatureFlagWriteRequest,
    request: Request,
    resources: PlatformResourcesDep,
    principal: FlagsManageDep,
) -> FeatureFlagResponse:
    database, redis = resources
    current_actor_id = actor_id(principal)
    async with database.transaction() as session:
        result = await PlatformService(session, redis).create_flag(body, current_actor_id)
        await record(
            session,
            AuditEvent(
                action="flags.created",
                actor_type=ActorType.ADMIN,
                actor_user_id=current_actor_id,
                target_type="feature_flag",
                target_id=result.key,
            ),
            context_from_request(request),
        )
        return result


@platform_admin_router.put(
    "/flags/{key}", response_model=FeatureFlagResponse, status_code=200, summary="Update a feature flag"
)
async def update_flag(
    key: str,
    body: FeatureFlagUpdateRequest,
    request: Request,
    resources: PlatformResourcesDep,
    principal: FlagsManageDep,
) -> FeatureFlagResponse:
    database, redis = resources
    current_actor_id = actor_id(principal)
    async with database.transaction() as session:
        result = await PlatformService(session, redis).update_flag(key, body, current_actor_id)
        await record(
            session,
            AuditEvent(
                action="flags.updated",
                actor_type=ActorType.ADMIN,
                actor_user_id=current_actor_id,
                target_type="feature_flag",
                target_id=key,
            ),
            context_from_request(request),
        )
        return result


@platform_admin_router.delete(
    "/flags/{key}", response_model=None, status_code=status.HTTP_204_NO_CONTENT, summary="Delete a feature flag"
)
async def delete_flag(
    key: str,
    body: FeatureFlagDeleteRequest,
    request: Request,
    resources: PlatformResourcesDep,
    principal: FlagsManageDep,
) -> None:
    database, redis = resources
    async with database.transaction() as session:
        await PlatformService(session, redis).delete_flag(key, body.version)
        await record(
            session,
            AuditEvent(
                action="flags.deleted",
                actor_type=ActorType.ADMIN,
                actor_user_id=principal.user_id,
                target_type="feature_flag",
                target_id=key,
            ),
            context_from_request(request),
        )


platform_router.include_router(platform_admin_router)
