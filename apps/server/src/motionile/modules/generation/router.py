from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse

from motionile.core.dependencies import CursorCodecDep, DatabaseDep
from motionile.core.errors import problem_responses
from motionile.core.idempotency import IdempotencyGuard, idempotent, read_key
from motionile.core.ratelimit.limiter import rate_limit
from motionile.modules.audit import context_from_request
from motionile.modules.auth import enforce_csrf
from motionile.modules.generation.dependencies import CurrentUserIdDep, GenerationServiceDep
from motionile.modules.generation.repository import JobFilter
from motionile.modules.generation.schemas import (
    ApproveRequest,
    EstimateRequest,
    EstimateView,
    JobCreateRequest,
    JobListQuery,
    JobPage,
    JobView,
    RegenerateRequest,
    ReviseRequest,
    StoryboardUpdateRequest,
    StoryboardView,
)

CREATE_SCOPE = "jobs.create"
REVISE_SCOPE = "jobs.revise"

jobs_router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
    dependencies=[Depends(enforce_csrf)],
    responses=problem_responses(status.HTTP_401_UNAUTHORIZED),
)
DEFAULT_LIMIT = [Depends(rate_limit("api.default"))]
CREATE_LIMIT = [Depends(rate_limit("jobs.create"))]
WRITE_LIMIT = [Depends(rate_limit("jobs.write"))]


@jobs_router.post(
    "/estimate",
    response_model=EstimateView,
    status_code=status.HTTP_200_OK,
    summary="Estimate the credits a video would cost and whether your balance covers it",
    dependencies=DEFAULT_LIMIT,
    responses=problem_responses(status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def estimate_job(
    body: EstimateRequest, user_id: CurrentUserIdDep, database: DatabaseDep, service: GenerationServiceDep
) -> EstimateView:
    async with database.transaction() as session:
        return await service.estimate(session, user_id, body)


@jobs_router.post(
    "",
    response_model=JobView,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a video from a catalog topic or a free-text query; reserves the estimated credits",
    dependencies=CREATE_LIMIT,
    responses=problem_responses(
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_402_PAYMENT_REQUIRED,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_409_CONFLICT,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    ),
)
async def create_job(  # noqa: PLR0913, PLR0917
    body: JobCreateRequest,
    request: Request,
    user_id: CurrentUserIdDep,
    database: DatabaseDep,
    service: GenerationServiceDep,
    guard: Annotated[IdempotencyGuard, Depends(idempotent(CREATE_SCOPE))],
) -> JSONResponse:
    async with database.transaction() as session:
        view = await service.create(session, user_id, body, read_key(request), context_from_request(request))
    return await guard.respond(view, status_code=status.HTTP_202_ACCEPTED, headers={"Location": f"/v1/jobs/{view.id}"})


@jobs_router.get(
    "",
    response_model=JobPage,
    status_code=status.HTTP_200_OK,
    summary="List your jobs, newest first",
    dependencies=DEFAULT_LIMIT,
    responses=problem_responses(status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def list_jobs(
    query: Annotated[JobListQuery, Query()],
    user_id: CurrentUserIdDep,
    database: DatabaseDep,
    cursors: CursorCodecDep,
    service: GenerationServiceDep,
) -> JobPage:
    cursor = cursors.decode(query.cursor) if query.cursor else None
    async with database.transaction() as session:
        page = await service.list_jobs(
            session, user_id, JobFilter(query.status, query.source, query.topic_id), cursor, query.limit
        )
    return JobPage(
        items=page.items, next_cursor=cursors.encode(page.next_cursor) if page.next_cursor is not None else None
    )


@jobs_router.get(
    "/{job_id}",
    response_model=JobView,
    status_code=status.HTTP_200_OK,
    summary="Get one of your jobs",
    dependencies=DEFAULT_LIMIT,
    responses=problem_responses(status.HTTP_404_NOT_FOUND),
)
async def get_job(
    job_id: UUID, user_id: CurrentUserIdDep, database: DatabaseDep, service: GenerationServiceDep
) -> JobView:
    async with database.transaction() as session:
        return await service.get(session, user_id, job_id)


@jobs_router.get(
    "/{job_id}/storyboard",
    response_model=StoryboardView,
    status_code=status.HTTP_200_OK,
    summary="Get the latest storyboard of a job with its deterministic issues and limits",
    dependencies=DEFAULT_LIMIT,
    responses=problem_responses(status.HTTP_404_NOT_FOUND),
)
async def get_storyboard(
    job_id: UUID, user_id: CurrentUserIdDep, database: DatabaseDep, service: GenerationServiceDep
) -> StoryboardView:
    async with database.transaction() as session:
        return await service.storyboard(session, user_id, job_id)


@jobs_router.put(
    "/{job_id}/storyboard",
    response_model=StoryboardView,
    status_code=status.HTTP_200_OK,
    summary="Save an edited storyboard as a new version while the job awaits approval",
    dependencies=WRITE_LIMIT,
    responses=problem_responses(
        status.HTTP_404_NOT_FOUND, status.HTTP_409_CONFLICT, status.HTTP_422_UNPROCESSABLE_CONTENT
    ),
)
async def update_storyboard(
    job_id: UUID,
    body: StoryboardUpdateRequest,
    user_id: CurrentUserIdDep,
    database: DatabaseDep,
    service: GenerationServiceDep,
) -> StoryboardView:
    async with database.transaction() as session:
        return await service.update_storyboard(session, user_id, job_id, body)


@jobs_router.post(
    "/{job_id}/storyboard/regenerate",
    response_model=JobView,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ask the planner for a new storyboard with your instructions while the job awaits approval",
    dependencies=WRITE_LIMIT,
    responses=problem_responses(
        status.HTTP_404_NOT_FOUND, status.HTTP_409_CONFLICT, status.HTTP_422_UNPROCESSABLE_CONTENT
    ),
)
async def regenerate_storyboard(
    job_id: UUID,
    body: RegenerateRequest,
    user_id: CurrentUserIdDep,
    database: DatabaseDep,
    service: GenerationServiceDep,
) -> JobView:
    async with database.transaction() as session:
        return await service.regenerate(session, user_id, job_id, body)


@jobs_router.post(
    "/{job_id}/approve",
    response_model=JobView,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Approve the current storyboard version and let the video continue",
    dependencies=WRITE_LIMIT,
    responses=problem_responses(
        status.HTTP_404_NOT_FOUND, status.HTTP_409_CONFLICT, status.HTTP_422_UNPROCESSABLE_CONTENT
    ),
)
async def approve_job(  # noqa: PLR0913, PLR0917
    job_id: UUID,
    body: ApproveRequest,
    request: Request,
    user_id: CurrentUserIdDep,
    database: DatabaseDep,
    service: GenerationServiceDep,
) -> JobView:
    async with database.transaction() as session:
        return await service.approve(session, user_id, job_id, body, context_from_request(request))


@jobs_router.post(
    "/{job_id}/cancel",
    response_model=JobView,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Cancel a job; queued and waiting jobs stop at once, running jobs stop at the next step",
    dependencies=WRITE_LIMIT,
    responses=problem_responses(status.HTTP_404_NOT_FOUND, status.HTTP_409_CONFLICT),
)
async def cancel_job(
    job_id: UUID, request: Request, user_id: CurrentUserIdDep, database: DatabaseDep, service: GenerationServiceDep
) -> JobView:
    async with database.transaction() as session:
        return await service.cancel(session, user_id, job_id, context_from_request(request))


@jobs_router.post(
    "/{job_id}/revise",
    response_model=JobView,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a new job that revises a completed video with your instructions",
    dependencies=CREATE_LIMIT,
    responses=problem_responses(
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_402_PAYMENT_REQUIRED,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_409_CONFLICT,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    ),
)
async def revise_job(  # noqa: PLR0913, PLR0917
    job_id: UUID,
    body: ReviseRequest,
    request: Request,
    user_id: CurrentUserIdDep,
    database: DatabaseDep,
    service: GenerationServiceDep,
    guard: Annotated[IdempotencyGuard, Depends(idempotent(REVISE_SCOPE))],
) -> JSONResponse:
    async with database.transaction() as session:
        view = await service.revise(session, user_id, job_id, body, read_key(request), context_from_request(request))
    return await guard.respond(view, status_code=status.HTTP_202_ACCEPTED, headers={"Location": f"/v1/jobs/{view.id}"})


@jobs_router.delete(
    "/{job_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a finished job together with its video files",
    dependencies=WRITE_LIMIT,
    responses=problem_responses(status.HTTP_404_NOT_FOUND, status.HTTP_409_CONFLICT),
)
async def delete_job(
    job_id: UUID, request: Request, user_id: CurrentUserIdDep, database: DatabaseDep, service: GenerationServiceDep
) -> Response:
    async with database.transaction() as session:
        await service.delete(session, user_id, job_id, context_from_request(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
