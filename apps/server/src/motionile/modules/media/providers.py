from collections.abc import Sequence

from motionile.core.config import AudioProviderName, Settings
from motionile.core.resources import Resources
from motionile.engine.audio.models import ProviderVoice
from motionile.engine.audio.providers.aligner import Aligner
from motionile.engine.audio.providers.base import (
    ProviderConfigurationError,
    Transcriber,
    TTSProvider,
    VoiceCatalog,
    VoiceCloner,
)
from motionile.engine.audio.providers.elevenlabs import (
    ElevenLabsApi,
    ElevenLabsConfig,
    ElevenLabsTranscriber,
    ElevenLabsTTS,
    ElevenLabsVoices,
)
from motionile.engine.audio.providers.fake import FakeTranscriber, FakeTTSProvider, FakeVoiceService
from motionile.engine.audio.providers.measure import FfmpegDurationMeter
from motionile.engine.audio.providers.openai import OpenAIApi, OpenAIConfig, OpenAITranscriber, OpenAITTS
from motionile.engine.ffmpeg import FfmpegTools

ELEVENLABS_API = "media.elevenlabs_api"
OPENAI_API = "media.openai_api"
FAKE_VOICE_SERVICE = "media.fake_voice_service"
OPENAI_VOICES = (
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "fable",
    "nova",
    "onyx",
    "sage",
    "shimmer",
    "verse",
)


class StaticVoiceCatalog:
    def __init__(self, voices: Sequence[ProviderVoice]) -> None:
        self._voices = tuple(voices)

    async def list_voices(self) -> Sequence[ProviderVoice]:
        return self._voices


def ffmpeg_tools(settings: Settings) -> FfmpegTools:
    return FfmpegTools(ffmpeg=settings.render.ffmpeg_path, ffprobe=settings.render.ffprobe_path)


def elevenlabs_api(resources: Resources) -> ElevenLabsApi:
    settings = resources.settings.elevenlabs
    key = settings.api_key
    if key is None:
        raise ProviderConfigurationError("ELEVENLABS_API_KEY is not set")
    config = ElevenLabsConfig(
        api_key=key,
        base_url=settings.api_base_url,
        tts_model=settings.tts_model,
        stt_model=settings.stt_model,
        cost_micros_per_1k_chars=settings.cost_micros_per_1k_chars,
    )
    return resources.shared_instance(
        ELEVENLABS_API, lambda: ElevenLabsApi(resources.provider_clients["elevenlabs"], config)
    )


def openai_api(resources: Resources) -> OpenAIApi:
    settings = resources.settings.openai
    key = settings.api_key
    if key is None:
        raise ProviderConfigurationError("OPENAI_API_KEY is not set")
    config = OpenAIConfig(
        api_key=key,
        base_url=settings.api_base_url,
        tts_model=settings.tts_model,
        transcribe_model=settings.transcribe_model,
        cost_micros_per_1k_chars=settings.cost_micros_per_1k_chars,
    )
    return resources.shared_instance(OPENAI_API, lambda: OpenAIApi(resources.provider_clients["openai"], config))


def fake_voice_service(resources: Resources) -> FakeVoiceService:
    return resources.shared_instance(FAKE_VOICE_SERVICE, FakeVoiceService)


def build_transcriber(resources: Resources, provider: AudioProviderName | None = None) -> Transcriber:
    settings = resources.settings
    if settings.is_fake_providers:
        return FakeTranscriber()
    selected = provider or settings.audio.transcriber
    if selected == "openai":
        return OpenAITranscriber(openai_api(resources))
    return ElevenLabsTranscriber(elevenlabs_api(resources))


def build_tts_provider(resources: Resources, provider: str | None = None) -> TTSProvider:
    settings = resources.settings
    if settings.is_fake_providers:
        return FakeTTSProvider()
    selected = provider or settings.audio.tts_provider
    meter = FfmpegDurationMeter(ffmpeg_tools(settings))
    if selected == "openai":
        return OpenAITTS(openai_api(resources), meter, Aligner(build_transcriber(resources), meter))
    if selected == "elevenlabs":
        return ElevenLabsTTS(elevenlabs_api(resources), meter)
    raise ProviderConfigurationError(f"the text-to-speech provider {selected!r} is not supported")


def build_voice_cloner(resources: Resources) -> VoiceCloner:
    if resources.settings.is_fake_providers:
        return fake_voice_service(resources)
    return ElevenLabsVoices(elevenlabs_api(resources))


def build_voice_catalog(resources: Resources, provider: AudioProviderName | None = None) -> VoiceCatalog:
    settings = resources.settings
    if settings.is_fake_providers:
        return fake_voice_service(resources)
    selected = provider or settings.audio.tts_provider
    if selected == "openai":
        return StaticVoiceCatalog(
            [ProviderVoice(voice, voice.capitalize(), None, {"category": "premade"}, None) for voice in OPENAI_VOICES]
        )
    return ElevenLabsVoices(elevenlabs_api(resources))
