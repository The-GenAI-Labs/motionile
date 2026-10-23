from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.modules.media.render_options import (
    RenderOptions,
    RenderOptionsRequest,
    ResolvedVoice,
    SynthesizeRequest,
    stored_options,
)


class VoiceLookup(Protocol):
    async def resolve_selectable(self, session: AsyncSession, user_id: UUID, voice_id: UUID) -> ResolvedVoice: ...


async def resolve_render_options(
    session: AsyncSession,
    user_id: UUID,
    request: RenderOptionsRequest,
    voices: VoiceLookup,
    *,
    default_fps: int,
) -> RenderOptions:
    voice: ResolvedVoice | None = None
    if isinstance(request.narration, SynthesizeRequest):
        voice = await voices.resolve_selectable(session, user_id, request.narration.voice_id)
    return stored_options(request, voice, default_fps)
