from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import StreamingResponse

from motionile.core.dependencies import DatabaseDep, SettingsDep
from motionile.core.errors import UnauthorizedError, problem_responses
from motionile.core.ratelimit.limiter import rate_limit
from motionile.core.security.rbac import Principal
from motionile.modules.access import RenderTestbedDep
from motionile.modules.audit import context_from_request
from motionile.modules.auth import enforce_csrf
from motionile.modules.media.dependencies import (
    GoldenCatalogDep,
    MediaServiceDep,
    RenderEventsDep,
    VoiceLookupDep,
)
from motionile.modules.media.domain import RenderSource
from motionile.modules.media.golden import GoldenComposition
from motionile.modules.media.render_bed_schemas import (
    BedMusicTrackList,
    GoldenCatalogView,
    GoldenCompositionView,
    GoldenName,
    GoldenRenderRequest,
    GoldenSceneView,
    RenderBedView,
    bed_track,
)
from motionile.modules.media.render_bed_upload import read_bed_upload
from motionile.modules.media.render_options import RenderOptionsRequest, SynthesizeRequest
from motionile.modules.media.render_stream import stream_render_events
from motionile.modules.media.schemas import RenderView
from motionile.modules.media.voice_lookup import resolve_render_options

testbed_router = APIRouter(
    prefix="/admin/render/testbed",
    tags=["admin-render-testbed"],
    dependencies=[Depends(enforce_csrf), Depends(rate_limit("api.default"))],
    responses=problem_responses(401, 403, 404, 422),
)
CREATE_LIMIT = [Depends(rate_limit("render.create"))]
EVENT_STREAM_HEADERS = {"Cache-Control": "no-store", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
EVENT_STREAM_RESPONSES: dict[int | str, dict[str, object]] = {
    200: {"description": "Server-sent events", "content": {"text/event-stream": {"schema": {"type": "string"}}}},
    **problem_responses(401, 403, 404),
}


def bed_user_id(principal: Principal) -> UUID:
    if principal.user_id is None:
        raise UnauthorizedError(code="unauthenticated")
    return principal.user_id


def golden_view(golden: GoldenComposition) -> GoldenCompositionView:
    return GoldenCompositionView(
        name=golden.name,
        title=golden.title,
        description=golden.description,
        language=golden.language,
        scene_ids=[scene.scene_id for scene in golden.scenes],
        scenes=[GoldenSceneView(scene_id=scene.scene_id, text=scene.text) for scene in golden.scenes],
    )


@testbed_router.get(
    "/golden",
    response_model=GoldenCatalogView,
    status_code=200,
    summary="List the golden compositions with their scene IDs and narration text",
)
async def list_golden_compositions(_: RenderTestbedDep, catalog: GoldenCatalogDep) -> GoldenCatalogView:
    return GoldenCatalogView(items=[golden_view(golden) for golden in await catalog.compositions()])


@testbed_router.post(
    "/golden/{name}",
    response_model=RenderView,
    status_code=202,
    summary="Render a golden composition with its own narration text",
    dependencies=CREATE_LIMIT,
    responses=problem_responses(429, 503),
)
async def create_golden_render(  # noqa: PLR0913, PLR0917
    name: Annotated[GoldenName, Path()],
    body: GoldenRenderRequest,
    request: Request,
    principal: RenderTestbedDep,
    catalog: GoldenCatalogDep,
    database: DatabaseDep,
    service: MediaServiceDep,
    voices: VoiceLookupDep,
    settings: SettingsDep,
) -> RenderView:
    user_id = bed_user_id(principal)
    golden = await catalog.load(name)
    narration = SynthesizeRequest(mode="synthesize", voice_id=body.voice_id, scenes=list(golden.scenes))
    options = RenderOptionsRequest(
        aspects=body.aspects,
        fps=body.fps,
        narration=narration,
        music_track_id=body.music_track_id,
        subtitles=body.subtitles,
        burn_in_subtitles=body.burn_in_subtitles,
    )
    async with database.transaction() as session:
        resolved = await resolve_render_options(session, user_id, options, voices, default_fps=settings.render.fps)
        return await service.create_render(
            session,
            user_id,
            golden.html,
            resolved,
            RenderSource.TESTBED,
            context=context_from_request(request),
        )


@testbed_router.get(
    "/music-tracks",
    response_model=BedMusicTrackList,
    status_code=200,
    summary="List the active music tracks for the test bed picker",
)
async def list_testbed_music_tracks(
    _: RenderTestbedDep, database: DatabaseDep, service: MediaServiceDep
) -> BedMusicTrackList:
    async with database.transaction() as session:
        tracks = await service.selectable_music(session)
    return BedMusicTrackList(items=[bed_track(track) for track in tracks])


@testbed_router.post(
    "",
    response_model=RenderView,
    status_code=202,
    summary="Submit a composition (multipart: composition, options and scene audio parts) to the render pipeline",
    dependencies=CREATE_LIMIT,
    responses=problem_responses(400, 413, 429, 503),
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["composition", "options"],
                        "properties": {
                            "composition": {"type": "string", "format": "binary"},
                            "options": {"type": "string", "description": "JSON of the render options"},
                        },
                        "additionalProperties": {"type": "string", "format": "binary"},
                    }
                }
            },
        }
    },
)
async def create_testbed_render(  # noqa: PLR0913, PLR0917
    request: Request,
    principal: RenderTestbedDep,
    database: DatabaseDep,
    service: MediaServiceDep,
    voices: VoiceLookupDep,
    settings: SettingsDep,
) -> RenderView:
    user_id = bed_user_id(principal)
    upload = await read_bed_upload(request)
    async with database.transaction() as session:
        resolved = await resolve_render_options(
            session, user_id, upload.options, voices, default_fps=settings.render.fps
        )
        return await service.create_render(
            session,
            user_id,
            upload.composition,
            resolved,
            RenderSource.TESTBED,
            audio_uploads=upload.audio,
            context=context_from_request(request),
        )


@testbed_router.get(
    "/{render_id}",
    response_model=RenderBedView,
    status_code=200,
    summary="Get a test bed render with its report, timings, error and playable renditions",
)
async def get_testbed_render(
    render_id: UUID, principal: RenderTestbedDep, database: DatabaseDep, service: MediaServiceDep
) -> RenderBedView:
    user_id = bed_user_id(principal)
    async with database.transaction() as session:
        render = await service.get_render(session, user_id, render_id)
        renditions = await service.renditions_for(session, user_id, render_id)
    return RenderBedView(**render.model_dump(), renditions=renditions)


@testbed_router.get(
    "/{render_id}/events",
    response_model=None,
    response_class=StreamingResponse,
    status_code=200,
    summary="Stream the progress of a test bed render as server-sent events",
    responses=EVENT_STREAM_RESPONSES,
)
async def stream_testbed_render(  # noqa: PLR0913, PLR0917
    render_id: UUID,
    request: Request,
    principal: RenderTestbedDep,
    database: DatabaseDep,
    service: MediaServiceDep,
    events: RenderEventsDep,
) -> StreamingResponse:
    user_id = bed_user_id(principal)
    async with database.transaction() as session:
        await service.get_render(session, user_id, render_id)
    stream = stream_render_events(
        database.transaction, service, events, user_id, render_id, is_disconnected=request.is_disconnected
    )
    return StreamingResponse(stream, media_type="text/event-stream", headers=EVENT_STREAM_HEADERS)


@testbed_router.post(
    "/{render_id}/cancel",
    response_model=RenderView,
    status_code=200,
    summary="Cancel a test bed render; finished renders are returned unchanged",
)
async def cancel_testbed_render(
    render_id: UUID, principal: RenderTestbedDep, database: DatabaseDep, service: MediaServiceDep
) -> RenderView:
    user_id = bed_user_id(principal)
    async with database.transaction() as session:
        return await service.cancel_render(session, user_id, render_id)
