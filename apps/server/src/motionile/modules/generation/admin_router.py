from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from motionile.core.dependencies import CursorCodecDep, DatabaseDep
from motionile.core.errors import problem_responses
from motionile.core.ratelimit.limiter import rate_limit
from motionile.modules.access import RequirePermission
from motionile.modules.audit import context_from_request
from motionile.modules.auth import enforce_csrf
from motionile.modules.generation.admin_repository import AdminJobFilter
from motionile.modules.generation.admin_schemas import (
    AdminJobDetail,
    AdminJobListQuery,
    AdminJobPage,
    AnalyticsQuery,
    JobAnalyticsView,
)
from motionile.modules.generation.dependencies import AdminJobsServiceDep, CurrentUserIdDep

JOBS_PERMISSION = "jobs.read_all"

admin_jobs_router = APIRouter(
    prefix="/admin",
    tags=["admin-jobs"],
    dependencies=[
        Depends(enforce_csrf),
        Depends(rate_limit("api.default")),
        Depends(RequirePermission(JOBS_PERMISSION)),
    ],
    responses=problem_responses(status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
)


@admin_jobs_router.get(
    "/jobs",
    response_model=AdminJobPage,
    status_code=status.HTTP_200_OK,
    summary="List the jobs of every user with their outcome and credits",
    responses=problem_responses(status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def list_admin_jobs(
    query: Annotated[AdminJobListQuery, Query()],
    database: DatabaseDep,
    cursors: CursorCodecDep,
    service: AdminJobsServiceDep,
) -> AdminJobPage:
    cursor = cursors.decode(query.cursor) if query.cursor else None
    job_filter = AdminJobFilter(query.status, query.source, query.user_id, query.created_from, query.created_to)
    async with database.transaction() as session:
        result = await service.list_jobs(session, job_filter, cursor, query.limit)
    return AdminJobPage(
        items=result.items,
        next_cursor=cursors.encode(result.next_cursor) if result.next_cursor is not None else None,
    )


@admin_jobs_router.get(
    "/jobs/{job_id}",
    response_model=AdminJobDetail,
    status_code=status.HTTP_200_OK,
    summary="Inspect one job: events, storyboard versions, scenes, reports, cost and trace link",
    responses=problem_responses(status.HTTP_404_NOT_FOUND),
)
async def get_admin_job(
    job_id: UUID,
    request: Request,
    admin_id: CurrentUserIdDep,
    database: DatabaseDep,
    service: AdminJobsServiceDep,
) -> AdminJobDetail:
    async with database.transaction() as session:
        return await service.detail(session, admin_id, job_id, context_from_request(request))


@admin_jobs_router.get(
    "/analytics/jobs",
    response_model=JobAnalyticsView,
    status_code=status.HTTP_200_OK,
    summary="Job outcomes per day, stage durations, repair and fallback rates, and cost against credits charged",
    responses=problem_responses(status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def get_job_analytics(
    query: Annotated[AnalyticsQuery, Query()], database: DatabaseDep, service: AdminJobsServiceDep
) -> JobAnalyticsView:
    async with database.transaction() as session:
        return await service.analytics(session, query)
