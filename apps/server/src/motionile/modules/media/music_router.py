from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from motionile.core.dependencies import CursorCodecDep, DatabaseDep
from motionile.core.errors import UnauthorizedError, problem_responses
from motionile.core.ratelimit.limiter import rate_limit
from motionile.modules.access import MusicManageDep
from motionile.modules.audit import AuditContext, context_from_request
from motionile.modules.auth import enforce_csrf
from motionile.modules.media.dependencies import MusicServiceDep
from motionile.modules.media.music_repository import MusicFilter
from motionile.modules.media.music_upload import MUSIC_UPLOAD_OPENAPI, read_music_upload
from motionile.modules.media.schemas import (
    MusicListQuery,
    MusicTrackPage,
    MusicTrackView,
    MusicUpdateRequest,
)

music_router = APIRouter(
    prefix="/admin/music",
    tags=["admin-music"],
    dependencies=[Depends(enforce_csrf), Depends(rate_limit("api.default"))],
    responses=problem_responses(401, 403, 404, 413, 422),
)
WRITE_LIMIT = [Depends(rate_limit("music.write"))]
UPLOAD_LIMITS = [Depends(rate_limit("music.write")), Depends(rate_limit("media.upload"))]


@dataclass(frozen=True, slots=True)
class AdminCall:
    actor_id: UUID
    context: AuditContext


def admin_call(request: Request, principal: MusicManageDep) -> AdminCall:
    if principal.user_id is None:
        raise UnauthorizedError(code="unauthenticated")
    return AdminCall(principal.user_id, context_from_request(request))


AdminCallDep = Annotated[AdminCall, Depends(admin_call)]


@music_router.get("", response_model=MusicTrackPage, status_code=200, summary="List music tracks, newest first")
async def list_music_tracks(
    query: Annotated[MusicListQuery, Query()],
    _: MusicManageDep,
    database: DatabaseDep,
    cursors: CursorCodecDep,
    service: MusicServiceDep,
) -> MusicTrackPage:
    cursor = cursors.decode(query.cursor) if query.cursor else None
    async with database.transaction() as session:
        page = await service.list_tracks(session, MusicFilter(query.mood, query.active), cursor, query.limit)
    return MusicTrackPage(
        items=page.items, next_cursor=cursors.encode(page.next_cursor) if page.next_cursor is not None else None
    )


@music_router.get("/{track_id}", response_model=MusicTrackView, status_code=200, summary="Get a music track")
async def get_music_track(
    track_id: UUID, _: MusicManageDep, database: DatabaseDep, service: MusicServiceDep
) -> MusicTrackView:
    async with database.transaction() as session:
        return await service.get(session, track_id)


@music_router.post(
    "",
    response_model=MusicTrackView,
    status_code=201,
    summary="Upload a licensed music track; it starts inactive unless activate is set",
    dependencies=UPLOAD_LIMITS,
    openapi_extra=MUSIC_UPLOAD_OPENAPI,
)
async def upload_music_track(
    request: Request, call: AdminCallDep, database: DatabaseDep, service: MusicServiceDep
) -> MusicTrackView:
    upload = await read_music_upload(request)
    async with database.transaction() as session:
        return await service.upload(session, call.actor_id, upload, call.context)


@music_router.patch(
    "/{track_id}",
    response_model=MusicTrackView,
    status_code=200,
    summary="Edit the metadata and license of a music track",
    dependencies=WRITE_LIMIT,
)
async def update_music_track(
    track_id: UUID,
    body: MusicUpdateRequest,
    call: AdminCallDep,
    database: DatabaseDep,
    service: MusicServiceDep,
) -> MusicTrackView:
    changes = {name: getattr(body, name) for name in body.model_fields_set}
    async with database.transaction() as session:
        return await service.update(session, call.actor_id, track_id, changes, call.context)


@music_router.post(
    "/{track_id}/activate",
    response_model=MusicTrackView,
    status_code=200,
    summary="Make a music track selectable for renders",
    dependencies=WRITE_LIMIT,
)
async def activate_music_track(
    track_id: UUID, call: AdminCallDep, database: DatabaseDep, service: MusicServiceDep
) -> MusicTrackView:
    async with database.transaction() as session:
        return await service.activate(session, call.actor_id, track_id, call.context)


@music_router.post(
    "/{track_id}/deactivate",
    response_model=MusicTrackView,
    status_code=200,
    summary="Stop offering a music track; rendered videos keep their mixed audio",
    dependencies=WRITE_LIMIT,
)
async def deactivate_music_track(
    track_id: UUID, call: AdminCallDep, database: DatabaseDep, service: MusicServiceDep
) -> MusicTrackView:
    async with database.transaction() as session:
        return await service.deactivate(session, call.actor_id, track_id, call.context)
