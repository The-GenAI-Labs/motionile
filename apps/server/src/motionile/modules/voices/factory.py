from datetime import timedelta

from motionile.core.resources import Resources
from motionile.engine.audio.providers.base import Transcriber
from motionile.modules.credits import CreditsService
from motionile.modules.media import (
    assets_for,
    build_transcriber,
    build_voice_catalog,
    build_voice_cloner,
    ffmpeg_tools,
    speech_for,
)
from motionile.modules.voices.clone import AttemptStore, FfmpegAudioProcessor
from motionile.modules.voices.clone_service import CloneService, EnqueueClone
from motionile.modules.voices.maintenance import VoiceMaintenance
from motionile.modules.voices.preview import PreviewGenerator
from motionile.modules.voices.repository import SqlVoiceRepository
from motionile.modules.voices.runner import CloneRunner
from motionile.modules.voices.runtime import PlatformRuntimeSettings
from motionile.modules.voices.service import VoicesService

CLONED_PROVIDER = "elevenlabs"
FAKE_PROVIDER = "fake"


def cloned_provider(resources: Resources) -> str:
    return FAKE_PROVIDER if resources.settings.is_fake_providers else CLONED_PROVIDER


def catalog_provider(resources: Resources) -> str:
    settings = resources.settings
    return FAKE_PROVIDER if settings.is_fake_providers else settings.audio.tts_provider


def previews_for(resources: Resources) -> PreviewGenerator:
    return PreviewGenerator(
        resources.database.transaction, assets_for(resources), speech_for(resources), SqlVoiceRepository
    )


def attempts_for(resources: Resources) -> AttemptStore:
    return AttemptStore(resources.redis_store, resources.clock)


def build_voices_service(resources: Resources) -> VoicesService:
    settings = resources.settings
    return VoicesService(
        transaction=resources.database.transaction,
        store_factory=SqlVoiceRepository,
        assets=assets_for(resources),
        storage=resources.storage,
        speech=speech_for(resources),
        cloner=lambda: build_voice_cloner(resources),
        catalog=lambda: build_voice_catalog(resources),
        previews=previews_for(resources),
        clock=resources.clock,
        preview_ttl=timedelta(seconds=settings.media.signed_url_ttl_seconds),
        catalog_provider=catalog_provider(resources),
    )


def build_clone_service(resources: Resources, enqueue: EnqueueClone) -> CloneService:
    settings = resources.settings
    return CloneService(
        transaction=resources.database.transaction,
        store_factory=SqlVoiceRepository,
        assets=assets_for(resources),
        attempts=attempts_for(resources),
        processor=FfmpegAudioProcessor(ffmpeg_tools(settings)),
        settings=settings.voices,
        billing=settings.billing,
        clock=resources.clock,
        credit_service=CreditsService(resources.clock, settings.billing),
        runtime=PlatformRuntimeSettings(resources.redis_store),
        enqueue=enqueue,
        provider=cloned_provider(resources),
    )


def build_clone_runner(resources: Resources, transcriber: Transcriber | None = None) -> CloneRunner:
    settings = resources.settings
    return CloneRunner(
        transaction=resources.database.transaction,
        store_factory=SqlVoiceRepository,
        assets=assets_for(resources),
        attempts=attempts_for(resources),
        speech=speech_for(resources),
        previews=previews_for(resources),
        transcriber=(lambda: transcriber) if transcriber is not None else (lambda: build_transcriber(resources)),
        cloner=lambda: build_voice_cloner(resources),
        credit_service=CreditsService(resources.clock, settings.billing),
        settings=settings.voices,
        clock=resources.clock,
    )


def build_maintenance(resources: Resources) -> VoiceMaintenance:
    return VoiceMaintenance(
        resources.database.transaction,
        SqlVoiceRepository,
        assets_for(resources),
        build_clone_runner(resources),
        resources.clock,
    )
