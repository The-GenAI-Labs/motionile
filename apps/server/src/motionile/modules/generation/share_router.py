import hashlib
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, Response, status

from motionile.core.dependencies import DatabaseDep
from motionile.core.errors import problem_responses
from motionile.core.ratelimit.limiter import rate_limit
from motionile.modules.auth import enforce_csrf
from motionile.modules.generation.dependencies import CurrentUserIdDep, ShareServiceDep
from motionile.modules.generation.share_schemas import ShareCreateRequest, SharedVideoView, ShareLinkView

share_router = APIRouter(
    prefix="/jobs",
    tags=["share"],
    dependencies=[Depends(enforce_csrf)],
    responses=problem_responses(status.HTTP_401_UNAUTHORIZED),
)
public_share_router = APIRouter(prefix="/share", tags=["share"])
MANAGE_LIMIT = [Depends(rate_limit("share.manage"))]
VIEW_LIMIT = [Depends(rate_limit("share.view"))]
UNKNOWN_CLIENT = "unknown"
NO_STORE = "no-store"


def viewer_of(request: Request) -> str:
    host = request.client.host if request.client is not None else UNKNOWN_CLIENT
    return hashlib.sha256(host.encode("utf-8")).hexdigest()


@share_router.post(
    "/{job_id}/share",
    response_model=ShareLinkView,
    status_code=status.HTTP_201_CREATED,
    summary="Create a public link for one rendition of a finished video; the previous link is revoked",
    dependencies=MANAGE_LIMIT,
    responses=problem_responses(
        status.HTTP_404_NOT_FOUND, status.HTTP_409_CONFLICT, status.HTTP_422_UNPROCESSABLE_CONTENT
    ),
)
async def create_share_link(
    job_id: UUID,
    body: ShareCreateRequest,
    user_id: CurrentUserIdDep,
    database: DatabaseDep,
    service: ShareServiceDep,
) -> ShareLinkView:
    async with database.transaction() as session:
        return await service.create(session, user_id, job_id, body)


@share_router.delete(
    "/{job_id}/share",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke every public link of a video",
    dependencies=MANAGE_LIMIT,
    responses=problem_responses(status.HTTP_404_NOT_FOUND),
)
async def revoke_share_links(
    job_id: UUID, user_id: CurrentUserIdDep, database: DatabaseDep, service: ShareServiceDep
) -> Response:
    async with database.transaction() as session:
        await service.revoke(session, user_id, job_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@public_share_router.get(
    "/{slug}",
    response_model=SharedVideoView,
    status_code=status.HTTP_200_OK,
    summary="Read a shared video by its link; no sign-in needed",
    dependencies=VIEW_LIMIT,
    responses=problem_responses(status.HTTP_404_NOT_FOUND, status.HTTP_429_TOO_MANY_REQUESTS),
)
async def get_shared_video(
    slug: Annotated[str, Path(min_length=1, max_length=64)],
    request: Request,
    response: Response,
    database: DatabaseDep,
    service: ShareServiceDep,
) -> SharedVideoView:
    response.headers["Cache-Control"] = NO_STORE
    async with database.transaction() as session:
        return await service.view(session, slug, viewer_of(request))
