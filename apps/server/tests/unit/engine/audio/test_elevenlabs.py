import base64
import itertools

import httpx
import pytest
from pydantic import SecretStr
from structlog.testing import capture_logs
from tests.unit.engine.audio.support import FAST_RETRY, Script, Sleeps, StaticMeter, json_response, safe_client

from motionile.engine.audio.models import CloneSample, SynthesisOptions, VoiceRef, WordTiming
from motionile.engine.audio.providers.base import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderNotFoundError,
    ProviderRateLimitedError,
    ProviderRejectedError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from motionile.engine.audio.providers.elevenlabs import (
    Alignment,
    ElevenLabsApi,
    ElevenLabsConfig,
    ElevenLabsTranscriber,
    ElevenLabsTTS,
    ElevenLabsVoices,
    price_for,
    words_from_alignment,
)

API_KEY = "xi-secret-key-value"
CONFIG = ElevenLabsConfig(api_key=SecretStr(API_KEY))
VOICE = VoiceRef("elevenlabs", "voice_123", "en")
OPTIONS = SynthesisOptions(language="en", speed=1.0, stability=0.5, output_format="mp3_44100_128")
AUDIO = b"ID3fake-mp3-bytes"


def alignment_for(text: str, step: float = 0.1) -> dict[str, object]:
    return {
        "characters": list(text),
        "character_start_times_seconds": [round(index * step, 3) for index in range(len(text))],
        "character_end_times_seconds": [round((index + 1) * step, 3) for index in range(len(text))],
    }


def speech_payload(text: str, **extra: object) -> dict[str, object]:
    return {
        "audio_base64": base64.b64encode(AUDIO).decode(),
        "alignment": alignment_for(text),
        "normalized_alignment": alignment_for(text),
        **extra,
    }


def build(
    *responses: httpx.Response | Exception, config: ElevenLabsConfig = CONFIG, duration_ms: int = 2000
) -> tuple[ElevenLabsApi, Script, Sleeps, StaticMeter]:
    script = Script(list(responses))
    sleeps = Sleeps()
    api = ElevenLabsApi(safe_client(script), config, sleep=sleeps, retry=FAST_RETRY)
    return api, script, sleeps, StaticMeter(duration_ms)


async def test_synthesis_posts_the_documented_request() -> None:
    api, script, _, meter = build(json_response(speech_payload("Hello big world")))

    result = await ElevenLabsTTS(api, meter).synthesize("Hello big world", VOICE, OPTIONS)

    request = script.last
    assert request.method == "POST"
    assert request.headers["host"] == "api.elevenlabs.io"
    assert request.url.path == "/v1/text-to-speech/voice_123/with-timestamps"
    assert dict(request.url.params) == {"output_format": "mp3_44100_128"}
    assert request.headers["xi-api-key"] == API_KEY
    assert request.headers["content-type"] == "application/json"
    assert script.last_json == {
        "text": "Hello big world",
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "speed": 1.0},
    }
    assert result.audio == AUDIO
    assert result.content_type == "audio/mpeg"
    assert result.model == "eleven_multilingual_v2"


async def test_character_alignment_becomes_word_timings_in_milliseconds() -> None:
    api, _, _, meter = build(json_response(speech_payload("Hello big world")))

    result = await ElevenLabsTTS(api, meter).synthesize("Hello big world", VOICE, OPTIONS)

    assert result.words == (
        WordTiming("Hello", 0, 500),
        WordTiming("big", 600, 900),
        WordTiming("world", 1000, 1500),
    )
    assert result.duration_ms == 2000
    assert meter.calls == 1


async def test_duration_comes_from_the_measured_audio_and_words_are_clamped_to_it() -> None:
    api, _, _, meter = build(json_response(speech_payload("Hello big world")), duration_ms=1200)

    result = await ElevenLabsTTS(api, meter).synthesize("Hello big world", VOICE, OPTIONS)

    assert result.duration_ms == 1200
    assert result.words[-1] == WordTiming("world", 1000, 1200)


async def test_characters_and_cost_are_billed_per_thousand_characters() -> None:
    text = "x" * 1500
    api, _, _, meter = build(json_response(speech_payload(text)))

    result = await ElevenLabsTTS(api, meter).synthesize(text, VOICE, OPTIONS)

    assert result.characters == 1500
    assert result.cost_micros_usd == 270_000


def test_price_rounds_up_to_whole_micro_dollars() -> None:
    assert price_for(1, 180_000) == 180
    assert price_for(0, 180_000) == 0
    assert price_for(1001, 1) == 2


async def test_speed_and_stability_are_clamped_to_the_documented_ranges() -> None:
    api, script, _, meter = build(json_response(speech_payload("Hi")))

    await ElevenLabsTTS(api, meter).synthesize("Hi", VOICE, SynthesisOptions("en", speed=3.0, stability=2.0))

    voice_settings = script.last_json["voice_settings"]
    assert isinstance(voice_settings, dict)
    assert voice_settings["speed"] == 1.2
    assert voice_settings["stability"] == 1.0


async def test_language_code_is_sent_only_for_models_that_accept_it() -> None:
    flash = ElevenLabsConfig(api_key=SecretStr(API_KEY), tts_model="eleven_flash_v2_5")
    api, script, _, meter = build(json_response(speech_payload("Hi")), config=flash)

    await ElevenLabsTTS(api, meter).synthesize("Hi", VoiceRef("elevenlabs", "v", "hi-IN"), OPTIONS)

    assert script.last_json["language_code"] == "hi"
    assert script.last_json["model_id"] == "eleven_flash_v2_5"
    default_api, default_script, _, _ = build(json_response(speech_payload("Hi")))
    await ElevenLabsTTS(default_api, meter).synthesize("Hi", VOICE, OPTIONS)
    assert "language_code" not in default_script.last_json


async def test_extra_response_fields_are_tolerated() -> None:
    payload = speech_payload("Hi", request_id="abc", future_field={"nested": True})
    api, _, _, meter = build(json_response(payload))

    result = await ElevenLabsTTS(api, meter).synthesize("Hi", VOICE, OPTIONS)

    assert result.words == (WordTiming("Hi", 0, 200),)


@pytest.mark.parametrize(
    "payload",
    [
        {"alignment": alignment_for("Hi")},
        {"audio_base64": "!!!not base64!!!", "alignment": alignment_for("Hi")},
        {"audio_base64": "", "alignment": alignment_for("Hi")},
        {"audio_base64": base64.b64encode(AUDIO).decode(), "alignment": None},
        {
            "audio_base64": base64.b64encode(AUDIO).decode(),
            "alignment": {"characters": ["a"], "character_start_times_seconds": [], "character_end_times_seconds": []},
        },
    ],
)
async def test_malformed_synthesis_responses_are_provider_response_errors(payload: dict[str, object]) -> None:
    api, _, _, meter = build(json_response(payload))

    with pytest.raises(ProviderResponseError):
        await ElevenLabsTTS(api, meter).synthesize("Hi", VOICE, OPTIONS)


async def test_an_unsupported_output_format_is_rejected_before_any_request() -> None:
    api, script, _, meter = build()

    with pytest.raises(ProviderRejectedError):
        await ElevenLabsTTS(api, meter).synthesize("Hi", VOICE, SynthesisOptions("en", output_format="pcm_16000"))

    assert script.requests == []


async def test_a_malformed_voice_id_is_rejected_before_any_request() -> None:
    api, script, _, meter = build()

    with pytest.raises(ProviderRejectedError):
        await ElevenLabsTTS(api, meter).synthesize("Hi", VoiceRef("elevenlabs", "../admin", "en"), OPTIONS)

    assert script.requests == []


def test_alignment_conversion_handles_runs_of_whitespace_and_edges() -> None:
    text = "  two  words\n"
    alignment = Alignment.model_validate(alignment_for(text))

    assert words_from_alignment(alignment) == (WordTiming("two", 200, 500), WordTiming("words", 700, 1200))


def test_alignment_conversion_covers_one_word_per_whitespace_run_for_unicode() -> None:
    text = "नमस्ते दुनिया"
    alignment = Alignment.model_validate(alignment_for(text, 0.05))

    words = words_from_alignment(alignment)

    assert [word.text for word in words] == text.split()
    assert all(left.end_ms <= right.start_ms for left, right in itertools.pairwise(words))


async def test_post_requests_are_not_retried_after_server_errors() -> None:
    api, script, sleeps, meter = build(
        httpx.Response(503, json={"detail": {"status": "overloaded"}}), json_response(speech_payload("Hi"))
    )

    with pytest.raises(ProviderUnavailableError) as raised:
        await ElevenLabsTTS(api, meter).synthesize("Hi", VOICE, OPTIONS)

    assert raised.value.reason == "overloaded"
    assert raised.value.code == "provider_unavailable"
    assert len(script.requests) == 1
    assert sleeps.delays == []


async def test_rate_limits_are_retried_honouring_retry_after_up_to_the_cap() -> None:
    api, script, sleeps, meter = build(
        httpx.Response(429, headers={"retry-after": "30"}),
        httpx.Response(429),
        json_response(speech_payload("Hi")),
    )

    result = await ElevenLabsTTS(api, meter).synthesize("Hi", VOICE, OPTIONS)

    assert result.words
    assert len(script.requests) == 3
    assert sleeps.delays == [1.0, 0.2]


async def test_rate_limit_error_is_raised_when_attempts_run_out() -> None:
    api, script, _, meter = build(*[httpx.Response(429) for _ in range(3)])

    with pytest.raises(ProviderRateLimitedError):
        await ElevenLabsTTS(api, meter).synthesize("Hi", VOICE, OPTIONS)

    assert len(script.requests) == 3


@pytest.mark.parametrize(
    ("status", "error_type", "code"),
    [
        (401, ProviderAuthenticationError, "provider_authentication_failed"),
        (403, ProviderAuthenticationError, "provider_authentication_failed"),
        (404, ProviderNotFoundError, "provider_not_found"),
        (422, ProviderRejectedError, "provider_rejected"),
        (400, ProviderRejectedError, "provider_rejected"),
        (504, ProviderTimeoutError, "provider_timeout"),
        (500, ProviderUnavailableError, "provider_unavailable"),
    ],
)
async def test_status_codes_map_to_stable_error_codes(status: int, error_type: type[Exception], code: str) -> None:
    api, _, _, meter = build(httpx.Response(status, json={"detail": {"status": "boom"}}))

    with pytest.raises(error_type) as raised:
        await ElevenLabsTTS(api, meter).synthesize("Hi", VOICE, OPTIONS)

    assert getattr(raised.value, "code", None) == code
    assert getattr(raised.value, "status_code", None) == status


async def test_transport_failures_map_to_timeout_and_unavailable() -> None:
    api, _, _, meter = build(httpx.ReadTimeout("slow"))
    with pytest.raises(ProviderTimeoutError):
        await ElevenLabsTTS(api, meter).synthesize("Hi", VOICE, OPTIONS)

    api, _, _, meter = build(httpx.ConnectError("refused"))
    with pytest.raises(ProviderUnavailableError):
        await ElevenLabsTTS(api, meter).synthesize("Hi", VOICE, OPTIONS)


async def test_a_blocked_endpoint_is_a_configuration_error() -> None:
    config = ElevenLabsConfig(api_key=SecretStr(API_KEY), base_url="http://api.elevenlabs.io")
    api, _, _, meter = build(config=config)

    with pytest.raises(ProviderConfigurationError):
        await ElevenLabsTTS(api, meter).synthesize("Hi", VOICE, OPTIONS)


async def test_the_api_key_never_reaches_logs_errors_or_reprs() -> None:
    api, _, _, meter = build(httpx.Response(401, json={"detail": {"status": "invalid_api_key", "message": API_KEY}}))

    with capture_logs() as logs, pytest.raises(ProviderAuthenticationError) as raised:
        await ElevenLabsTTS(api, meter).synthesize("Hi", VOICE, OPTIONS)

    rendered = [str(raised.value), repr(raised.value), repr(api), repr(api.http), repr(CONFIG), str(logs)]
    assert all(API_KEY not in value for value in rendered)
    assert logs
    assert all(entry["event"] == "audio_provider.request_failed" for entry in logs)


async def test_transcription_posts_multipart_with_word_timestamps() -> None:
    payload = {
        "language_code": "eng",
        "text": "Hello world",
        "words": [
            {"text": "Hello", "start": 0.1, "end": 0.5, "type": "word"},
            {"text": " ", "start": 0.5, "end": 0.55, "type": "spacing"},
            {"text": "(laughter)", "start": 0.55, "end": 0.7, "type": "audio_event"},
            {"text": "world", "start": 0.7, "end": 1.2, "type": "word"},
            {"text": "ghost", "type": "word"},
        ],
    }
    api, script, _, _ = build(json_response(payload))

    transcript = await ElevenLabsTranscriber(api).transcribe(b"RIFFdata", "speech.wav", "en-US")

    body = script.last.content
    assert script.last.url.path == "/v1/speech-to-text"
    assert script.last.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert b'name="model_id"\r\n\r\nscribe_v1' in body
    assert b'name="timestamps_granularity"\r\n\r\nword' in body
    assert b'name="language_code"\r\n\r\nen' in body
    assert b'name="file"; filename="speech.wav"' in body
    assert b"RIFFdata" in body
    assert transcript.text == "Hello world"
    assert transcript.words == (WordTiming("Hello", 100, 500), WordTiming("world", 700, 1200))


async def test_transcription_omits_language_when_it_is_unknown() -> None:
    api, script, _, _ = build(json_response({"text": "", "words": []}))

    transcript = await ElevenLabsTranscriber(api).transcribe(b"x", "a.wav", None)

    assert b"language_code" not in script.last.content
    assert transcript.words == ()


async def test_voice_listing_maps_languages_and_labels() -> None:
    payload: dict[str, object] = {
        "voices": [
            {
                "voice_id": "v1",
                "name": "Rachel",
                "category": "premade",
                "labels": {"language": "en", "accent": "american", "empty": None},
                "preview_url": "https://cdn.example/rachel.mp3",
                "unknown": 1,
            },
            {"voice_id": "v2", "name": "Priya", "labels": {}, "verified_languages": [{"language": "hi"}]},
            {"voice_id": "v3", "name": "Quiet", "labels": {}},
        ]
    }
    api, script, _, _ = build(json_response(payload))

    voices = await ElevenLabsVoices(api).list_voices()

    assert script.last.method == "GET"
    assert script.last.url.path == "/v1/voices"
    assert [(voice.provider_voice_id, voice.name, voice.language) for voice in voices] == [
        ("v1", "Rachel", "en"),
        ("v2", "Priya", "hi"),
        ("v3", "Quiet", None),
    ]
    assert dict(voices[0].labels) == {"language": "en", "accent": "american"}
    assert voices[0].preview_url == "https://cdn.example/rachel.mp3"


async def test_voice_listing_is_retried_after_a_server_error() -> None:
    api, script, sleeps, _ = build(httpx.Response(500), json_response({"voices": []}))

    assert await ElevenLabsVoices(api).list_voices() == []
    assert len(script.requests) == 2
    assert sleeps.delays == [0.1]


async def test_clone_posts_multipart_with_name_files_and_labels() -> None:
    api, script, _, _ = build(json_response({"voice_id": "clone_9", "requires_verification": False}))
    samples = [CloneSample("a.wav", b"AAAA"), CloneSample("b.wav", b"BBBB", "audio/wav")]

    voice_id = await ElevenLabsVoices(api).clone("My voice", "en", samples, "a description")

    body = script.last.content
    assert voice_id == "clone_9"
    assert script.last.url.path == "/v1/voices/add"
    assert b'name="name"\r\n\r\nMy voice' in body
    assert b'name="description"\r\n\r\na description' in body
    assert b'name="labels"\r\n\r\n{"language": "en"}' in body
    assert body.count(b'name="files"') == 2
    assert b'filename="a.wav"' in body
    assert b"AAAA" in body
    assert b"BBBB" in body


async def test_clone_is_never_retried_and_validates_the_sample_count() -> None:
    api, script, _, _ = build(httpx.Response(502))

    with pytest.raises(ProviderUnavailableError):
        await ElevenLabsVoices(api).clone("v", None, [CloneSample("a.wav", b"x")], None)
    assert len(script.requests) == 1

    with pytest.raises(ProviderRejectedError):
        await ElevenLabsVoices(api).clone("v", None, [], None)
    assert len(script.requests) == 1


async def test_delete_uses_the_voice_endpoint_and_reports_missing_voices() -> None:
    api, script, _, _ = build(
        json_response({"status": "ok"}), httpx.Response(404, json={"detail": {"status": "voice_not_found"}})
    )

    await ElevenLabsVoices(api).delete("clone_9")
    assert script.last.method == "DELETE"
    assert script.last.url.path == "/v1/voices/clone_9"

    with pytest.raises(ProviderNotFoundError) as raised:
        await ElevenLabsVoices(api).delete("clone_9")
    assert raised.value.reason == "voice_not_found"
