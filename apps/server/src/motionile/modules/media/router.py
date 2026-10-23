from uuid import UUID

from fastapi import APIRouter, Depends, Response

from motionile.core.dependencies import DatabaseDep
from motionile.core.errors import problem_responses
from motionile.core.ratelimit.limiter import rate_limit
from motionile.modules.auth import enforce_csrf
from motionile.modules.media.delivery import MediaSessionGrant
from motionile.modules.media.dependencies import CurrentUserIdDep, MediaServiceDep
from motionile.modules.media.schemas import MediaSessionView, RenderView, RenditionListView

NO_STORE = "no-store"

media_router = APIRouter(
    prefix="/media",
    tags=["media"],
    dependencies=[Depends(enforce_csrf)],
    responses=problem_responses(401, 503),
)
renders_router = APIRouter(
    prefix="/renders",
    tags=["renders"],
    dependencies=[Depends(enforce_csrf), Depends(rate_limit("api.default"))],
    responses=problem_responses(401, 404, 422),
)


def apply_cookies(response: Response, grant: MediaSessionGrant) -> None:
    for cookie in grant.cookies:
        response.set_cookie(
            cookie.name,
            cookie.value,
            max_age=cookie.max_age,
            path=cookie.path,
            domain=cookie.domain,
            secure=cookie.secure,
            httponly=cookie.http_only,
            samesite=cookie.same_site,
        )


@media_router.get(
    "/session",
    response_model=MediaSessionView,
    status_code=200,
    summary="Refresh the media session: signed cookies in CloudFront mode, the mode alone otherwise",
    dependencies=[Depends(rate_limit("media.session"))],
)
async def get_session(user_id: CurrentUserIdDep, service: MediaServiceDep, response: Response) -> MediaSessionView:
    grant = service.media_session(user_id)
    apply_cookies(response, grant)
    response.headers["Cache-Control"] = NO_STORE
    return MediaSessionView(mode=grant.mode, expires_at=grant.expires_at)


@renders_router.get("/{render_id}", response_model=RenderView, status_code=200, summary="Get one of your renders")
async def get_render(
    render_id: UUID, user_id: CurrentUserIdDep, database: DatabaseDep, service: MediaServiceDep
) -> RenderView:
    async with database.transaction() as session:
        return await service.get_render(session, user_id, render_id)


@renders_router.get(
    "/{render_id}/renditions",
    response_model=RenditionListView,
    status_code=200,
    summary="List the renditions of one of your renders with playable URLs",
)
async def list_renditions(
    render_id: UUID, user_id: CurrentUserIdDep, database: DatabaseDep, service: MediaServiceDep
) -> RenditionListView:
    async with database.transaction() as session:
        items = await service.renditions_for(session, user_id, render_id)
    return RenditionListView(items=items)
