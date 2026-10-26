from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from motionile.core.dependencies import DatabaseDep
from motionile.core.errors import problem_responses
from motionile.core.ratelimit.limiter import rate_limit
from motionile.modules.auth import enforce_csrf
from motionile.modules.generation.dependencies import CurrentUserIdDep, GenerationServiceDep, JobEventsDep
from motionile.modules.generation.stream import JobStreamSource, parse_last_event_id, stream_job_events
from motionile.modules.media import StreamSlotsDep

events_router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
    dependencies=[Depends(enforce_csrf), Depends(rate_limit("api.default"))],
    responses=problem_responses(401),
)
EVENT_STREAM_HEADERS = {"Cache-Control": "no-store", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
EVENT_STREAM_RESPONSES: dict[int | str, dict[str, object]] = {
    200: {"description": "Server-sent events", "content": {"text/event-stream": {"schema": {"type": "string"}}}},
    **problem_responses(401, 404, 429),
}


@events_router.get(
    "/{job_id}/events",
    response_model=None,
    response_class=StreamingResponse,
    status_code=200,
    summary="Stream the progress of one of your jobs as server-sent events",
    responses=EVENT_STREAM_RESPONSES,
)
async def follow_job_events(  # noqa: PLR0913, PLR0917
    job_id: UUID,
    request: Request,
    user_id: CurrentUserIdDep,
    database: DatabaseDep,
    service: GenerationServiceDep,
    events: JobEventsDep,
    slots: StreamSlotsDep,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID", max_length=64)] = None,
) -> StreamingResponse:
    async with database.transaction() as session:
        await service.get(session, user_id, job_id)
    lease = await slots.acquire(user_id)
    stream = stream_job_events(
        JobStreamSource(database.transaction, service, user_id, job_id),
        events,
        job_id,
        after=parse_last_event_id(last_event_id),
        is_disconnected=request.is_disconnected,
        lease=lease,
    )
    return StreamingResponse(
        stream, media_type="text/event-stream", headers=EVENT_STREAM_HEADERS, background=BackgroundTask(lease.release)
    )
