from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from motionile.core.dependencies import CursorCodecDep
from motionile.core.errors import UnauthorizedError, problem_responses
from motionile.core.ratelimit.limiter import rate_limit
from motionile.modules.access import VoicesManageDep
from motionile.modules.audit import AuditContext, context_from_request
from motionile.modules.auth import enforce_csrf
from motionile.modules.voices.dependencies import VoicesServiceDep
from motionile.modules.voices.domain import VoiceKind
from motionile.modules.voices.repository import VoiceFilter
from motionile.modules.voices.schemas import (
    AdminVoiceListQuery,
    AdminVoicePage,
    AdminVoiceView,
    VoiceSyncView,
    VoiceUpdateRequest,
)

voices_admin_router = APIRouter(
    prefix="/admin/voices",
    tags=["admin-voices"],
    dependencies=[Depends(enforce_csrf), Depends(rate_limit("api.default"))],
    responses=problem_responses(401, 403, 404, 422),
)


@dataclass(frozen=True, slots=True)
class AdminCall:
    actor_id: UUID
    context: AuditContext


def admin_call(request: Request, principal: VoicesManageDep) -> AdminCall:
    if principal.user_id is None:
        raise UnauthorizedError(code="unauthenticated")
    return AdminCall(principal.user_id, context_from_request(request))


AdminCallDep = Annotated[AdminCall, Depends(admin_call)]


@voices_admin_router.get(
    "",
    response_model=AdminVoicePage,
    status_code=status.HTTP_200_OK,
    summary="List the built-in voices in any status",
)
async def list_builtin_voices(
    query: Annotated[AdminVoiceListQuery, Query()],
    _: VoicesManageDep,
    service: VoicesServiceDep,
    cursors: CursorCodecDep,
) -> AdminVoicePage:
    cursor = cursors.decode(query.cursor) if query.cursor else None
    voice_filter = VoiceFilter(query.language, VoiceKind.BUILTIN.value, query.status)
    listing = await service.admin_list(voice_filter, cursor, query.limit)
    return AdminVoicePage(
        items=listing.items,
        next_cursor=cursors.encode(listing.next_cursor) if listing.next_cursor is not None else None,
    )


@voices_admin_router.post(
    "/sync",
    response_model=VoiceSyncView,
    status_code=status.HTTP_200_OK,
    summary="Add new provider voices as disabled built-in voices; existing voices keep their curation",
    responses=problem_responses(502),
)
async def sync_builtin_voices(call: AdminCallDep, service: VoicesServiceDep) -> VoiceSyncView:
    return await service.admin_sync(call.actor_id, call.context)


@voices_admin_router.patch(
    "/{voice_id}",
    response_model=AdminVoiceView,
    status_code=status.HTTP_200_OK,
    summary="Curate a built-in voice: name, language, tags and whether it is exposed",
    responses=problem_responses(502),
)
async def update_builtin_voice(
    voice_id: UUID, body: VoiceUpdateRequest, call: AdminCallDep, service: VoicesServiceDep
) -> AdminVoiceView:
    changes = {name: getattr(body, name) for name in body.model_fields_set}
    return await service.admin_update(call.actor_id, voice_id, changes, call.context)


@voices_admin_router.post(
    "/{voice_id}/preview",
    response_model=AdminVoiceView,
    status_code=status.HTTP_200_OK,
    summary="Regenerate the preview clip of a built-in voice",
    responses=problem_responses(502),
)
async def regenerate_builtin_voice_preview(
    voice_id: UUID, call: AdminCallDep, service: VoicesServiceDep
) -> AdminVoiceView:
    return await service.admin_regenerate_preview(call.actor_id, voice_id, call.context)
