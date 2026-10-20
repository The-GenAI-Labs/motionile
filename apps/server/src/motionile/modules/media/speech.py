from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from motionile.core.config import Settings
from motionile.engine.audio.models import SynthesisOptions, VoiceRef
from motionile.engine.audio.providers.base import TTSProvider
from motionile.engine.audio.synthesis import CachedSynthesizer, NarratedAudio
from motionile.modules.media.ports import Transaction
from motionile.modules.media.speech_cache import SpeechUsageSink, SqlSynthesisCache

type SpeechResult = NarratedAudio
type ProviderSource = Callable[[str | None], TTSProvider]

OPENAI_OUTPUT_FORMAT = "mp3"
FAKE_OUTPUT_FORMAT = "wav"
DEFAULT_SPEED = 1.0
DEFAULT_STABILITY = 0.5


class SpeechService:
    def __init__(
        self, transaction: Transaction, cache: SqlSynthesisCache, settings: Settings, providers: ProviderSource
    ) -> None:
        self._transaction = transaction
        self._cache = cache
        self._settings = settings
        self._providers = providers

    def default_options(
        self, provider: str, language: str, *, speed: float = DEFAULT_SPEED, stability: float = DEFAULT_STABILITY
    ) -> SynthesisOptions:
        if self._settings.is_fake_providers:
            output_format = FAKE_OUTPUT_FORMAT
        elif provider == "openai":
            output_format = OPENAI_OUTPUT_FORMAT
        else:
            output_format = self._settings.elevenlabs.output_format
        return SynthesisOptions(language=language, speed=speed, stability=stability, output_format=output_format)

    async def synthesize_text(
        self, voice: VoiceRef, text: str, options: SynthesisOptions, *, user_id: UUID
    ) -> SpeechResult:
        provider = self._providers(voice.provider)
        synthesizer = CachedSynthesizer(provider, self._cache, SpeechUsageSink(self._transaction, user_id))
        return await synthesizer.synthesize(text, voice, options)

    async def delete_cache_for_voice(self, provider: str, provider_voice_id: str) -> int:
        return await self._cache.evict_voice(provider, provider_voice_id)

    async def prune_cache(self, older_than: datetime) -> int:
        return await self._cache.evict_unused(older_than)
