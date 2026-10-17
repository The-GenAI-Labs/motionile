from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from motionile.core.dependencies import CursorCodecDep, ResourcesDep
from motionile.core.errors import problem_responses
from motionile.core.ratelimit.limiter import rate_limit
from motionile.modules.access import AnalyticsReadDep, AuditReadDep
from motionile.modules.admin.schemas import AnalyticsResponse, AuditEntryResponse, AuditListResponse, AuditQuery
from motionile.modules.admin.service import AdminInsightsService
from motionile.modules.audit import ActorType, AuditEvent, context_from_request, record
from motionile.modules.auth import enforce_csrf

admin_insights_router = APIRouter(
    prefix="/admin",
    tags=["admin-insights"],
    dependencies=[Depends(enforce_csrf), Depends(rate_limit("api.default"))],
    responses=problem_responses(401, 403, 404, 422),
)


@admin_insights_router.get("/audit", response_model=AuditListResponse, status_code=200, summary="List audit entries")
async def list_audit_entries(
    query: Annotated[AuditQuery, Query()],
    resources: ResourcesDep,
    cursor_codec: CursorCodecDep,
    request: Request,
    principal: AuditReadDep,
) -> AuditListResponse:
    cursor = cursor_codec.decode(query.cursor) if query.cursor else None
    async with resources.database.transaction() as session:
        result = await AdminInsightsService(
            session, resources.redis_store, resources.clock, cursor_codec
        ).audit_entries(query, cursor)
        await record(
            session,
            AuditEvent(
                action="audit.listed",
                actor_type=ActorType.ADMIN,
                actor_user_id=principal.user_id,
                target_type="audit",
            ),
            context_from_request(request),
        )
        return result


@admin_insights_router.get(
    "/audit/{entry_id}", response_model=AuditEntryResponse, status_code=200, summary="Get an audit entry"
)
async def get_audit_entry(
    entry_id: UUID, request: Request, resources: ResourcesDep, principal: AuditReadDep
) -> AuditEntryResponse:
    async with resources.database.transaction() as session:
        result = await AdminInsightsService(
            session, resources.redis_store, resources.clock, resources.cursor_codec
        ).audit_entry(entry_id)
        await record(
            session,
            AuditEvent(
                action="audit.read",
                actor_type=ActorType.ADMIN,
                actor_user_id=principal.user_id,
                target_type="audit",
                target_id=str(entry_id),
            ),
            context_from_request(request),
        )
        return result


@admin_insights_router.get(
    "/analytics", response_model=AnalyticsResponse, status_code=200, summary="Get platform analytics"
)
async def get_analytics(request: Request, resources: ResourcesDep, principal: AnalyticsReadDep) -> AnalyticsResponse:
    async with resources.database.transaction() as session:
        result = await AdminInsightsService(
            session, resources.redis_store, resources.clock, resources.cursor_codec
        ).analytics()
        await record(
            session,
            AuditEvent(
                action="analytics.read",
                actor_type=ActorType.ADMIN,
                actor_user_id=principal.user_id,
                target_type="analytics",
            ),
            context_from_request(request),
        )
        return result
