from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.alerts import raise_alert
from motionile.core.resources import Resources
from motionile.modules.media import AssetInUseError, AssetNotFoundError, assets_for, build_voice_cloner, speech_for
from motionile.modules.users import export_registry, preference_guards, purge_registry
from motionile.modules.voices.models import Voice, VoiceConsent
from motionile.modules.voices.preview import delete_provider_voice
from motionile.modules.voices.repository import SqlVoiceRepository
from motionile.modules.voices.selectable import ensure_voice_selectable

logger = structlog.get_logger(__name__)

HOOK_NAME = "voices"


def voice_record(voice: Voice) -> dict[str, Any]:
    return {
        "id": str(voice.id),
        "kind": voice.kind,
        "provider": voice.provider,
        "name": voice.name,
        "language": voice.language,
        "status": voice.status,
        "failure_code": voice.failure_code,
        "labels": dict(voice.labels),
        "created_at": voice.created_at.isoformat(),
        "updated_at": voice.updated_at.isoformat(),
    }


def consent_record(consent: VoiceConsent) -> dict[str, Any]:
    return {
        "id": str(consent.id),
        "voice_id": str(consent.voice_id) if consent.voice_id is not None else None,
        "voice_reference": str(consent.voice_reference),
        "statement_version": consent.statement_version,
        "statement_sha256": consent.statement_sha256.hex(),
        "accepted_at": consent.accepted_at.isoformat(),
        "ip": str(consent.ip) if consent.ip is not None else None,
        "user_agent": consent.user_agent,
        "consent_asset_id": str(consent.consent_asset_id),
        "challenge_sentence": consent.challenge_sentence,
        "transcript": consent.transcript,
        "match_percent": consent.match_percent,
        "sample_count": consent.sample_count,
        "sample_total_ms": consent.sample_total_ms,
        "created_at": consent.created_at.isoformat(),
    }


async def export_user_voices(session: AsyncSession, user_id: UUID) -> object:
    store = SqlVoiceRepository(session)
    return {
        "voices": [voice_record(voice) for voice in await store.cloned_of(user_id)],
        "consents": [consent_record(consent) for consent in await store.consents_of(user_id)],
    }


async def purge_user_voices(resources: Resources, session: AsyncSession, user_id: UUID) -> None:
    voices = await SqlVoiceRepository(session).cloned_of(user_id)
    assets = assets_for(resources)
    speech = speech_for(resources)
    for voice in voices:
        provider_voice_id = voice.provider_voice_id
        if provider_voice_id is not None:
            try:
                await delete_provider_voice(build_voice_cloner(resources), provider_voice_id)
            except Exception:
                logger.exception("voices.purge_provider_delete_failed", voice_id=str(voice.id))
                raise_alert(
                    "voice_provider_delete_failed",
                    provider=voice.provider,
                    provider_voice_id=provider_voice_id,
                    voice_id=str(voice.id),
                )
            try:
                await speech.delete_cache_for_voice(voice.provider, provider_voice_id)
            except Exception:
                logger.exception("voices.purge_cache_delete_failed", voice_id=str(voice.id))
        if voice.preview_asset_id is not None:
            try:
                await assets.delete(session, None, voice.preview_asset_id)
            except (AssetNotFoundError, AssetInUseError):
                logger.warning("voices.purge_preview_not_removed", voice_id=str(voice.id))


def register_hooks() -> None:
    purge_registry.register(HOOK_NAME, purge_user_voices)
    export_registry.register(HOOK_NAME, export_user_voices)
    preference_guards.register_default_voice(ensure_voice_selectable)
