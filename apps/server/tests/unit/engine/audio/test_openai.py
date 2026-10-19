import httpx
import pytest
from pydantic import SecretStr
from tests.unit.engine.audio.support import (
    FAST_RETRY,
    Script,
    ScriptedTranscriber,
    Sleeps,
    StaticMeter,
    json_response,
    safe_client,
)

from motionile.engine.audio.models import SynthesisOptions, VoiceRef, WordTiming
from motionile.engine.audio.providers.aligner import Aligner
from motionile.engine.audio.providers.base import (
    ProviderAuthenticationError,
    ProviderRejectedError,
    ProviderResponseError,
)
from motionile.engine.audio.providers.openai import (
    OpenAIApi,
    OpenAIConfig,
    OpenAITranscriber,
    OpenAITTS,
    parse_transcription,
    price_for,
)

API_KEY = "sk-secret-openai-key"
CONFIG = OpenAIConfig(api_key=SecretStr(API_KEY))
VOICE = VoiceRef("openai", "alloy", "en")
OPTIONS = SynthesisOptions(language="en", speed=1.25, output_format="mp3")
AUDIO = b"ID3openai-mp3"


def build(*responses: httpx.Response | Exception, config: OpenAIConfig = CONFIG) -> tuple[OpenAIApi, Script, Sleeps]:
    script = Script(list(responses))
    sleeps = Sleeps()
    return OpenAIApi(safe_client(script), config, sleep=sleeps, retry=FAST_RETRY), script, sleeps


def provider(api: OpenAIApi, heard: list[WordTiming], duration_ms: int = 2000) -> tuple[OpenAITTS, ScriptedTranscriber]:
    transcriber = ScriptedTranscriber(heard)
    meter = StaticMeter(duration_ms)
    return OpenAITTS(api, meter, Aligner(transcriber, meter)), transcriber


async def test_speech_request_shape_for_a_model_without_speed_support() -> None:
    api, script, _ = build(httpx.Response(200, content=AUDIO, headers={"content-type": "audio/mpeg"}))
    tts, _ = provider(api, [WordTiming("hello", 0, 400)])

    result = await tts.synthesize("Hello world", VOICE, OPTIONS)

    assert script.last.method == "POST"
    assert script.last.url.path == "/v1/audio/speech"
    assert script.last.headers["authorization"] == f"Bearer {API_KEY}"
    assert script.last.headers["accept"] == "audio/mpeg"
    assert script.last_json == {
        "model": "gpt-4o-mini-tts",
        "input": "Hello world",
        "voice": "alloy",
        "response_format": "mp3",
    }
    assert result.audio == AUDIO
    assert result.content_type == "audio/mpeg"
    assert result.model == "gpt-4o-mini-tts"


async def test_speed_is_sent_and_clamped_for_models_that_support_it() -> None:
    config = OpenAIConfig(api_key=SecretStr(API_KEY), tts_model="tts-1")
    api, script, _ = build(httpx.Response(200, content=AUDIO), config=config)
    tts, _ = provider(api, [])

    await tts.synthesize("Hello", VOICE, SynthesisOptions("en", speed=9.0, output_format="mp3"))

    assert script.last_json["speed"] == 4.0


async def test_word_timings_come_from_the_aligner_over_the_generated_audio() -> None:
    api, _, _ = build(httpx.Response(200, content=AUDIO))
    heard = [WordTiming("hello", 100, 500), WordTiming("world", 600, 1000)]
    tts, transcriber = provider(api, heard, duration_ms=1500)

    result = await tts.synthesize("Hello, world!", VOICE, OPTIONS)

    assert OpenAITTS.returns_native_timestamps is False
    assert result.words == (WordTiming("Hello,", 100, 500), WordTiming("world!", 600, 1000))
    assert result.duration_ms == 1500
    assert transcriber.calls == [("speech.mp3", "en")]


async def test_characters_and_cost() -> None:
    api, _, _ = build(httpx.Response(200, content=AUDIO))
    tts, _ = provider(api, [])

    result = await tts.synthesize("x" * 2000, VOICE, OPTIONS)

    assert result.characters == 2000
    assert result.cost_micros_usd == 30_000
    assert price_for(1, 15_000) == 15


async def test_long_text_unsupported_formats_and_bad_voices_are_rejected_locally() -> None:
    api, script, _ = build()
    tts, _ = provider(api, [])

    with pytest.raises(ProviderRejectedError):
        await tts.synthesize("x" * 4097, VOICE, OPTIONS)
    with pytest.raises(ProviderRejectedError):
        await tts.synthesize("Hi", VOICE, SynthesisOptions("en", output_format="pcm"))
    with pytest.raises(ProviderRejectedError):
        await tts.synthesize("Hi", VoiceRef("openai", "a b", "en"), OPTIONS)

    assert script.requests == []


async def test_empty_audio_is_a_response_error() -> None:
    api, _, _ = build(httpx.Response(200, content=b""))
    tts, _ = provider(api, [])

    with pytest.raises(ProviderResponseError):
        await tts.synthesize("Hi", VOICE, OPTIONS)


async def test_authentication_failures_are_stable_errors() -> None:
    api, _, _ = build(httpx.Response(401, json={"error": {"code": "invalid_api_key", "message": API_KEY}}))
    tts, _ = provider(api, [])

    with pytest.raises(ProviderAuthenticationError) as raised:
        await tts.synthesize("Hi", VOICE, OPTIONS)

    assert raised.value.reason == "invalid_api_key"
    assert API_KEY not in str(raised.value) + repr(raised.value) + repr(api)


async def test_rate_limits_are_retried() -> None:
    api, script, sleeps = build(httpx.Response(429, headers={"retry-after": "0.5"}), httpx.Response(200, content=AUDIO))
    tts, _ = provider(api, [])

    await tts.synthesize("Hi", VOICE, OPTIONS)

    assert len(script.requests) == 2
    assert sleeps.delays == [0.5]


async def test_transcription_requests_word_level_verbose_json() -> None:
    payload = {
        "task": "transcribe",
        "language": "english",
        "duration": 1.2,
        "text": "Hello world",
        "words": [{"word": "Hello", "start": 0.0, "end": 0.42}, {"word": " world", "start": 0.5, "end": 1.2}],
    }
    api, script, _ = build(json_response(payload))

    transcript = await OpenAITranscriber(api).transcribe(b"RIFF", "consent.wav", "en-GB")

    body = script.last.content
    assert script.last.url.path == "/v1/audio/transcriptions"
    assert script.last.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert b'name="model"\r\n\r\nwhisper-1' in body
    assert b'name="response_format"\r\n\r\nverbose_json' in body
    assert b'name="timestamp_granularities[]"\r\n\r\nword' in body
    assert b'name="language"\r\n\r\nen' in body
    assert b'filename="consent.wav"' in body
    assert transcript.text == "Hello world"
    assert transcript.words == (WordTiming("Hello", 0, 420), WordTiming("world", 500, 1200))


def test_transcription_without_words_is_empty_and_malformed_payloads_fail() -> None:
    assert parse_transcription({"text": "hi"}).words == ()
    with pytest.raises(ProviderResponseError):
        parse_transcription({"words": [{"word": "x"}]})
    with pytest.raises(ProviderResponseError):
        parse_transcription([])
