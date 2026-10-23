from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.modules.media import ResolvedVoice
from motionile.modules.voices.exceptions import VoiceNotAvailableError
from motionile.modules.voices.repository import SqlVoiceRepository, StoreFactory
from motionile.modules.voices.selectable import selectable_voice


class VoiceLookupImpl:
    def __init__(self, factory: StoreFactory = SqlVoiceRepository) -> None:
        self._factory = factory

    async def resolve_selectable(self, session: AsyncSession, user_id: UUID, voice_id: UUID) -> ResolvedVoice:
        voice = await selectable_voice(session, user_id, voice_id, self._factory)
        provider_voice_id = voice.provider_voice_id
        if provider_voice_id is None:
            raise VoiceNotAvailableError
        return ResolvedVoice(
            voice_id=voice.id,
            provider=voice.provider,
            provider_voice_id=provider_voice_id,
            language=voice.language,
        )
