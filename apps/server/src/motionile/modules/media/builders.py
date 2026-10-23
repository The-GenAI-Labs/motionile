from collections.abc import Awaitable, Callable
from datetime import timedelta

from motionile.core.resources import Resources
from motionile.engine.audio.audio_validation import AudioUploadLimits, ValidatedAudio, validate_audio_upload
from motionile.modules.media.assets import AssetService
from motionile.modules.media.delivery import MediaDelivery, build_delivery
from motionile.modules.media.music import MusicService
from motionile.modules.media.music_audio import FfmpegMusicProcessor
from motionile.modules.media.pipeline import PipelineDeps, RenderPipeline, RenderToolchain
from motionile.modules.media.providers import build_transcriber, build_tts_provider, ffmpeg_tools
from motionile.modules.media.render_commands import (
    UPLOAD_MAX_BYTES,
    UPLOAD_MIN_DURATION_MS,
    RenderCommandPorts,
    RenderCommands,
    RenderDispatch,
)
from motionile.modules.media.render_events import RenderEvents
from motionile.modules.media.render_repository import SqlRenderJobRepository
from motionile.modules.media.speech import SpeechService
from motionile.modules.media.speech_cache import SqlSynthesisCache
from motionile.modules.media.stream_slots import StreamSlots

DELIVERY_KEY = "media.delivery"
ASSETS_KEY = "media.assets"
EVENTS_KEY = "media.render_events"
SLOTS_KEY = "media.stream_slots"
MUSIC_KEY = "media.music"
SPEECH_KEY = "media.speech"


def delivery_for(resources: Resources) -> MediaDelivery:
    return resources.shared_instance(
        DELIVERY_KEY, lambda: build_delivery(resources.settings, resources.storage, resources.clock)
    )


def assets_for(resources: Resources) -> AssetService:
    return resources.shared_instance(ASSETS_KEY, lambda: AssetService(resources.storage))


def music_service_for(resources: Resources) -> MusicService:
    settings = resources.settings
    return resources.shared_instance(
        MUSIC_KEY,
        lambda: MusicService(
            assets_for(resources),
            resources.storage,
            FfmpegMusicProcessor(ffmpeg_tools(settings), settings.render.work_directory),
            preview_ttl=timedelta(seconds=settings.media.signed_url_ttl_seconds),
        ),
    )


def speech_for(resources: Resources) -> SpeechService:
    return resources.shared_instance(
        SPEECH_KEY,
        lambda: SpeechService(
            resources.database.transaction,
            SqlSynthesisCache(resources.database.transaction, assets_for(resources), resources.clock),
            resources.settings,
            lambda provider: build_tts_provider(resources, provider),
        ),
    )


def render_events_for(resources: Resources) -> RenderEvents:
    return resources.shared_instance(EVENTS_KEY, lambda: RenderEvents(resources.redis_store))


def stream_slots_for(resources: Resources) -> StreamSlots:
    return resources.shared_instance(SLOTS_KEY, lambda: StreamSlots(resources.redis_store, resources.clock))


def audio_check_for(resources: Resources) -> Callable[[bytes], Awaitable[ValidatedAudio]]:
    tools = ffmpeg_tools(resources.settings)
    limits = AudioUploadLimits(
        max_bytes=UPLOAD_MAX_BYTES,
        min_duration_ms=UPLOAD_MIN_DURATION_MS,
        max_duration_ms=resources.settings.render.max_duration_ms,
    )

    async def check(data: bytes) -> ValidatedAudio:
        return await validate_audio_upload(tools, data, limits)

    return check


def render_commands_for(resources: Resources, dispatch: RenderDispatch) -> RenderCommands:
    return RenderCommands(
        RenderCommandPorts(
            assets=assets_for(resources),
            music=music_service_for(resources),
            storage=resources.storage,
            events=render_events_for(resources),
            settings=resources.settings,
            clock=resources.clock,
            dispatch=dispatch,
            audio_check=audio_check_for(resources),
            speech=speech_for(resources),
            transcriber=build_transcriber(resources),
        )
    )


def render_pipeline_for(resources: Resources, toolchain_for: Callable[[int], RenderToolchain]) -> RenderPipeline:
    return RenderPipeline(
        PipelineDeps(
            transaction=resources.database.transaction,
            storage=resources.storage,
            assets=assets_for(resources),
            speech=speech_for(resources),
            music=music_service_for(resources),
            transcriber=build_transcriber(resources),
            toolchain_for=toolchain_for,
            events=render_events_for(resources),
            settings=resources.settings,
            clock=resources.clock,
            store_factory=SqlRenderJobRepository,
        )
    )
