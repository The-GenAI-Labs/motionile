from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.engine.audio.models import VoiceRef
from motionile.engine.audio.providers.base import ProviderNotFoundError, VoiceCloner
from motionile.modules.media import (
    AssetKind,
    AssetNotFoundError,
    AssetService,
    AssetSpec,
    AssetView,
    SpeechService,
    voice_preview_key,
)
from motionile.modules.voices.ports import Transaction
from motionile.modules.voices.repository import StoreFactory

PREVIEW_TEXTS = {
    "en": "Hello, this is a preview of my voice. I can narrate your explainer videos clearly and calmly.",
    "hi": "नमस्ते, यह मेरी आवाज़ का एक छोटा नमूना है। मैं आपके वीडियो को साफ़ और शांत स्वर में सुना सकती हूँ।",
}
FALLBACK_LANGUAGE = "en"
EXTENSIONS = {
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/ogg": "ogg",
    "audio/aac": "aac",
    "audio/flac": "flac",
}
FALLBACK_EXTENSION = "bin"


def preview_text(language: str) -> str:
    base = language.split("-", 1)[0].lower()
    return PREVIEW_TEXTS.get(base, PREVIEW_TEXTS[FALLBACK_LANGUAGE])


def preview_extension(content_type: str) -> str:
    return EXTENSIONS.get(content_type, FALLBACK_EXTENSION)


async def delete_provider_voice(cloner: VoiceCloner, provider_voice_id: str) -> None:
    try:
        await cloner.delete(provider_voice_id)
    except ProviderNotFoundError:
        return


class PreviewGenerator:
    def __init__(
        self, transaction: Transaction, assets: AssetService, speech: SpeechService, store_factory: StoreFactory
    ) -> None:
        self._transaction = transaction
        self._assets = assets
        self._speech = speech
        self._store_factory = store_factory

    async def generate(
        self, voice_id: UUID, provider: str, provider_voice_id: str, language: str, *, user_id: UUID
    ) -> AssetView:
        result = await self._speech.synthesize_text(
            VoiceRef(provider, provider_voice_id, language),
            preview_text(language),
            self._speech.default_options(provider, language),
            user_id=user_id,
        )
        key = voice_preview_key(voice_id, preview_extension(result.content_type))
        async with self._transaction() as session:
            await self._discard_previous(session, voice_id, key)
        async with self._transaction() as session:
            return await self._assets.store_bytes(
                session,
                result.audio,
                AssetSpec(
                    key=key, kind=AssetKind.AUDIO, content_type=result.content_type, duration_ms=result.duration_ms
                ),
            )

    async def _discard_previous(self, session: AsyncSession, voice_id: UUID, key: str) -> None:
        voice = await self._store_factory(session).get(voice_id)
        previous = voice.preview_asset_id if voice is not None else None
        sitting_on_key = await self._assets.find_by_key(session, None, key)
        stale = [previous] if previous is not None else []
        if sitting_on_key is not None and sitting_on_key.id != previous:
            stale.append(sitting_on_key.id)
        for asset_id in stale:
            try:
                await self._assets.delete(session, None, asset_id)
            except AssetNotFoundError:
                continue
