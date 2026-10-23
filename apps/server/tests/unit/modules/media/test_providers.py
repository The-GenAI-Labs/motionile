from collections.abc import AsyncIterator

import pytest
from pydantic import SecretStr
from tests.fakes.resources import make_resources
from tests.fakes.settings import make_settings

from motionile.core.config import (
    AppEnv,
    AppSettings,
    AudioSettings,
    ElevenLabsSettings,
    OpenAISettings,
    ProvidersMode,
    Settings,
)
from motionile.core.resources import Resources
from motionile.engine.audio.models import CloneSample
from motionile.engine.audio.providers.base import ProviderConfigurationError
from motionile.engine.audio.providers.elevenlabs import ElevenLabsTranscriber, ElevenLabsTTS, ElevenLabsVoices
from motionile.engine.audio.providers.fake import FakeTranscriber, FakeTTSProvider, FakeVoiceService
from motionile.engine.audio.providers.openai import OpenAITranscriber, OpenAITTS
from motionile.modules.media import (
    build_transcriber,
    build_tts_provider,
    build_voice_catalog,
    build_voice_cloner,
    ffmpeg_tools,
)
from motionile.modules.media.providers import OPENAI_VOICES, StaticVoiceCatalog

KEY = SecretStr("k" * 32)


def live(
    audio: AudioSettings | None = None,
    elevenlabs: ElevenLabsSettings | None = None,
    openai: OpenAISettings | None = None,
) -> Settings:
    return Settings(
        app=AppSettings(env=AppEnv.CI, providers_mode=ProvidersMode.LIVE),
        audio=audio or AudioSettings(),
        elevenlabs=elevenlabs or ElevenLabsSettings(),
        openai=openai or OpenAISettings(),
    )


async def resources_for(settings: Settings) -> AsyncIterator[Resources]:
    built = make_resources(settings)
    yield built
    await built.aclose()


@pytest.fixture
async def fake_resources() -> AsyncIterator[Resources]:
    async for built in resources_for(make_settings()):
        yield built


@pytest.fixture
async def elevenlabs_resources() -> AsyncIterator[Resources]:
    async for built in resources_for(live(elevenlabs=ElevenLabsSettings(api_key=KEY))):
        yield built


@pytest.fixture
async def openai_resources() -> AsyncIterator[Resources]:
    settings = live(
        audio=AudioSettings(tts_provider="openai", transcriber="openai"), openai=OpenAISettings(api_key=KEY)
    )
    async for built in resources_for(settings):
        yield built


@pytest.fixture
async def keyless_resources() -> AsyncIterator[Resources]:
    async for built in resources_for(live()):
        yield built


def test_fake_mode_builds_the_engine_fakes(fake_resources: Resources) -> None:
    assert isinstance(build_tts_provider(fake_resources), FakeTTSProvider)
    assert isinstance(build_tts_provider(fake_resources, "elevenlabs"), FakeTTSProvider)
    assert isinstance(build_transcriber(fake_resources), FakeTranscriber)
    assert isinstance(build_voice_cloner(fake_resources), FakeVoiceService)
    assert isinstance(build_voice_catalog(fake_resources), FakeVoiceService)


def test_fake_mode_transcriber_consults_the_consent_text_source(fake_resources: Resources) -> None:
    transcriber = build_transcriber(fake_resources)

    assert isinstance(transcriber, FakeTranscriber)
    assert transcriber.text_source is not None


def test_fake_mode_shares_one_voice_service_between_the_cloner_and_the_catalog(fake_resources: Resources) -> None:
    assert build_voice_cloner(fake_resources) is build_voice_catalog(fake_resources)
    assert build_voice_cloner(fake_resources) is build_voice_cloner(fake_resources)


async def test_a_voice_cloned_in_fake_mode_shows_up_in_the_catalog(fake_resources: Resources) -> None:
    voice_id = await build_voice_cloner(fake_resources).clone("Mine", "en", [CloneSample("a.wav", b"abc")], None)

    voices = await build_voice_catalog(fake_resources).list_voices()

    assert voice_id in {voice.provider_voice_id for voice in voices}


async def test_each_fake_provider_is_fresh_so_call_logs_do_not_accumulate(fake_resources: Resources) -> None:
    first = build_tts_provider(fake_resources)
    second = build_tts_provider(fake_resources)

    assert first is not second


def test_live_mode_builds_elevenlabs_by_default(elevenlabs_resources: Resources) -> None:
    provider = build_tts_provider(elevenlabs_resources)

    assert isinstance(provider, ElevenLabsTTS)
    assert provider.model == "eleven_multilingual_v2"
    assert isinstance(build_transcriber(elevenlabs_resources), ElevenLabsTranscriber)
    assert isinstance(build_voice_cloner(elevenlabs_resources), ElevenLabsVoices)
    assert isinstance(build_voice_catalog(elevenlabs_resources), ElevenLabsVoices)


def test_live_elevenlabs_uses_the_audio_provider_client(elevenlabs_resources: Resources) -> None:
    client = elevenlabs_resources.provider_clients["elevenlabs"]

    assert client.allowed_hosts == frozenset({"api.elevenlabs.io"})
    assert client.settings.max_response_bytes >= 64 * 1024 * 1024
    assert client.settings.read_timeout_seconds >= 120


def test_live_mode_builds_openai_when_selected(openai_resources: Resources) -> None:
    provider = build_tts_provider(openai_resources)

    assert isinstance(provider, OpenAITTS)
    assert isinstance(build_transcriber(openai_resources), OpenAITranscriber)
    assert openai_resources.provider_clients["openai"].allowed_hosts == frozenset({"api.openai.com"})


def test_a_voice_can_pin_its_own_provider(openai_resources: Resources) -> None:
    with pytest.raises(ProviderConfigurationError):
        build_tts_provider(openai_resources, "elevenlabs")


async def test_the_openai_catalog_lists_the_builtin_voices(openai_resources: Resources) -> None:
    catalog = build_voice_catalog(openai_resources)

    assert isinstance(catalog, StaticVoiceCatalog)
    voices = await catalog.list_voices()
    assert [voice.provider_voice_id for voice in voices] == list(OPENAI_VOICES)
    assert all(voice.preview_url is None for voice in voices)


def test_live_mode_without_a_key_is_a_configuration_error(keyless_resources: Resources) -> None:
    with pytest.raises(ProviderConfigurationError, match="ELEVENLABS_API_KEY"):
        build_tts_provider(keyless_resources)
    with pytest.raises(ProviderConfigurationError, match="ELEVENLABS_API_KEY"):
        build_transcriber(keyless_resources)
    with pytest.raises(ProviderConfigurationError, match="ELEVENLABS_API_KEY"):
        build_voice_cloner(keyless_resources)
    with pytest.raises(ProviderConfigurationError, match="OPENAI_API_KEY"):
        build_tts_provider(keyless_resources, "openai")


def test_an_unknown_provider_is_a_configuration_error(elevenlabs_resources: Resources) -> None:
    with pytest.raises(ProviderConfigurationError, match="not supported"):
        build_tts_provider(elevenlabs_resources, "azure")


def test_the_key_is_never_part_of_a_provider_repr(elevenlabs_resources: Resources) -> None:
    provider = build_tts_provider(elevenlabs_resources)

    assert KEY.get_secret_value() not in repr(provider)
    assert KEY.get_secret_value() not in repr(vars(provider))


def test_the_ffmpeg_tools_follow_render_settings() -> None:
    tools = ffmpeg_tools(make_settings())

    assert (tools.ffmpeg, tools.ffprobe) == ("ffmpeg", "ffprobe")
