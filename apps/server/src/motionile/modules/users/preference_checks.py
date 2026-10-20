from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.errors import ValidationAppError

type DefaultVoiceGuard = Callable[[AsyncSession, UUID, UUID], Awaitable[None]]


class DefaultVoiceUnavailableError(ValidationAppError):
    default_code = "voice_not_available"
    title = "Voice not available"


class PreferenceGuards:
    def __init__(self) -> None:
        self._default_voice: DefaultVoiceGuard | None = None

    def register_default_voice(self, guard: DefaultVoiceGuard) -> None:
        if self._default_voice is not None:
            raise ValueError("the default voice guard is already registered")
        self._default_voice = guard

    async def check_default_voice(self, session: AsyncSession, user_id: UUID, voice_id: UUID) -> None:
        if self._default_voice is None:
            raise DefaultVoiceUnavailableError
        await self._default_voice(session, user_id, voice_id)


preference_guards = PreferenceGuards()
