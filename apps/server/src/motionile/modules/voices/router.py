from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile

from motionile.core.dependencies import CursorCodecDep, SettingsDep
from motionile.core.errors import problem_responses
from motionile.core.idempotency import IdempotencyGuard, idempotent
from motionile.core.ratelimit.limiter import rate_limit
from motionile.modules.audit import context_from_request
from motionile.modules.auth import enforce_csrf
from motionile.modules.media import (
    FORM_OVERHEAD_BYTES,
    FormLimits,
    file_upload_schema,
    missing,
    multipart_body,
    parse_bounded_form,
    read_upload_part,
    unique_parts,
)
from motionile.modules.voices.dependencies import CloneServiceDep, CurrentUserIdDep, VoicesServiceDep
from motionile.modules.voices.exceptions import AudioTooLargeError
from motionile.modules.voices.repository import VoiceFilter
from motionile.modules.voices.schemas import (
    CloneAttemptView,
    CloneStartRequest,
    CloneStartView,
    CloneSubmitRequest,
    VoiceListQuery,
    VoicePage,
    VoicePreviewView,
    VoiceView,
)

SUBMIT_SCOPE = "voices.clone.submit"
FILE_FIELD = "file"
UPLOAD_FIELDS = frozenset({FILE_FIELD})
CONSENT_BODY = "Body_voices_replace_consent_recording"
SAMPLE_BODY = "Body_voices_add_clone_sample"
CONSENT_OPENAPI = multipart_body(CONSENT_BODY, file_upload_schema(CONSENT_BODY))
SAMPLE_OPENAPI = multipart_body(SAMPLE_BODY, file_upload_schema(SAMPLE_BODY))

voices_router = APIRouter(
    prefix="/voices",
    tags=["voices"],
    dependencies=[Depends(enforce_csrf), Depends(rate_limit("api.default"))],
    responses=problem_responses(401, 404, 422),
)
CLONE_LIMIT = [Depends(rate_limit("voices.clone"))]
UPLOAD_LIMIT = [Depends(rate_limit("voices.upload"))]


async def audio_upload(request: Request, settings: SettingsDep) -> bytes:
    limit = settings.voices.sample_max_bytes
    limits = FormLimits(limit + FORM_OVERHEAD_BYTES, max_files=2, max_fields=len(UPLOAD_FIELDS) + 2)
    form = await parse_bounded_form(request, limits, AudioTooLargeError, required_field=FILE_FIELD)
    try:
        file = unique_parts(form, UPLOAD_FIELDS).get(FILE_FIELD)
        if not isinstance(file, UploadFile):
            raise missing(FILE_FIELD)
        return await read_upload_part(file, limit, AudioTooLargeError)
    finally:
        await form.close()


AudioUploadDep = Annotated[bytes, Depends(audio_upload)]


@voices_router.post(
    "/clones",
    response_model=CloneStartView,
    status_code=status.HTTP_201_CREATED,
    summary="Accept the consent statement and open a voice cloning attempt",
    dependencies=CLONE_LIMIT,
    responses=problem_responses(409),
)
async def start_voice_clone(
    body: CloneStartRequest, request: Request, user_id: CurrentUserIdDep, service: CloneServiceDep
) -> CloneStartView:
    return await service.start(user_id, body.statement_version, context_from_request(request))


@voices_router.get(
    "/clones/{attempt_id}",
    response_model=CloneAttemptView,
    status_code=status.HTTP_200_OK,
    summary="Get the state of a voice cloning attempt",
)
async def get_voice_clone_attempt(
    attempt_id: UUID, user_id: CurrentUserIdDep, service: CloneServiceDep
) -> CloneAttemptView:
    return await service.state(user_id, attempt_id)


@voices_router.put(
    "/clones/{attempt_id}/consent-recording",
    response_model=CloneAttemptView,
    status_code=status.HTTP_200_OK,
    summary="Upload or replace the recording of the consent sentence",
    dependencies=UPLOAD_LIMIT,
    responses=problem_responses(409, 413),
    openapi_extra=CONSENT_OPENAPI,
)
async def replace_consent_recording(
    attempt_id: UUID, user_id: CurrentUserIdDep, content: AudioUploadDep, service: CloneServiceDep
) -> CloneAttemptView:
    return await service.replace_consent_recording(user_id, attempt_id, content)


@voices_router.post(
    "/clones/{attempt_id}/samples",
    response_model=CloneAttemptView,
    status_code=status.HTTP_201_CREATED,
    summary="Add a voice sample to a cloning attempt",
    dependencies=UPLOAD_LIMIT,
    responses=problem_responses(409, 413),
    openapi_extra=SAMPLE_OPENAPI,
)
async def add_clone_sample(
    attempt_id: UUID, user_id: CurrentUserIdDep, content: AudioUploadDep, service: CloneServiceDep
) -> CloneAttemptView:
    return await service.add_sample(user_id, attempt_id, content)


@voices_router.delete(
    "/clones/{attempt_id}/samples/{sample_id}",
    response_model=CloneAttemptView,
    status_code=status.HTTP_200_OK,
    summary="Remove a voice sample from a cloning attempt",
    responses=problem_responses(409),
)
async def remove_clone_sample(
    attempt_id: UUID, sample_id: UUID, user_id: CurrentUserIdDep, service: CloneServiceDep
) -> CloneAttemptView:
    return await service.remove_sample(user_id, attempt_id, sample_id)


@voices_router.post(
    "/clones/{attempt_id}/submit",
    response_model=VoiceView,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a cloning attempt; the voice is created in the background",
    responses=problem_responses(402, 409),
)
async def submit_voice_clone(  # noqa: PLR0913, PLR0917
    attempt_id: UUID,
    body: CloneSubmitRequest,
    request: Request,
    user_id: CurrentUserIdDep,
    service: CloneServiceDep,
    guard: Annotated[IdempotencyGuard, Depends(idempotent(SUBMIT_SCOPE))],
) -> JSONResponse:
    voice = await service.submit(user_id, attempt_id, body, context_from_request(request))
    return await guard.respond(voice, status_code=status.HTTP_202_ACCEPTED)


@voices_router.get(
    "",
    response_model=VoicePage,
    status_code=status.HTTP_200_OK,
    summary="List the voices you can select: ready built-in voices and your own cloned voices",
)
async def list_voices(
    query: Annotated[VoiceListQuery, Query()],
    user_id: CurrentUserIdDep,
    service: VoicesServiceDep,
    cursors: CursorCodecDep,
) -> VoicePage:
    cursor = cursors.decode(query.cursor) if query.cursor else None
    listing = await service.list_voices(user_id, VoiceFilter(query.language, query.kind), cursor, query.limit)
    return VoicePage(
        items=listing.items,
        next_cursor=cursors.encode(listing.next_cursor) if listing.next_cursor is not None else None,
    )


@voices_router.get(
    "/{voice_id}",
    response_model=VoiceView,
    status_code=status.HTTP_200_OK,
    summary="Get a voice you can select or one of your own cloned voices",
)
async def get_voice(voice_id: UUID, user_id: CurrentUserIdDep, service: VoicesServiceDep) -> VoiceView:
    return await service.get_voice(user_id, voice_id)


@voices_router.get(
    "/{voice_id}/preview",
    response_model=VoicePreviewView,
    status_code=status.HTTP_200_OK,
    summary="Get a short-lived URL of the voice preview clip",
)
async def get_voice_preview(voice_id: UUID, user_id: CurrentUserIdDep, service: VoicesServiceDep) -> VoicePreviewView:
    return await service.preview_url(user_id, voice_id)


@voices_router.delete(
    "/{voice_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one of your cloned voices at the provider and in storage",
    responses=problem_responses(409, 502),
)
async def delete_voice(voice_id: UUID, request: Request, user_id: CurrentUserIdDep, service: VoicesServiceDep) -> None:
    await service.delete_voice(user_id, voice_id, context_from_request(request))
