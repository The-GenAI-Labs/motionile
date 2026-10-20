from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.modules.voices.domain import VoiceKind, VoiceStatus
from motionile.modules.voices.exceptions import VoiceNotAvailableError
from motionile.modules.voices.models import Voice
from motionile.modules.voices.repository import SqlVoiceRepository, StoreFactory


async def selectable_voice(session: AsyncSession, user_id: UUID, voice_id: UUID, factory: StoreFactory) -> Voice:
    voice = await factory(session).get_visible(user_id, voice_id)
    if voice is None or voice.status != VoiceStatus.READY.value or voice.provider_voice_id is None:
        raise VoiceNotAvailableError
    if voice.kind == VoiceKind.CLONED.value and voice.owner_user_id != user_id:
        raise VoiceNotAvailableError
    return voice


async def ensure_voice_selectable(session: AsyncSession, user_id: UUID, voice_id: UUID) -> None:
    await selectable_voice(session, user_id, voice_id, SqlVoiceRepository)
