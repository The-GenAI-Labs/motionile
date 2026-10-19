import asyncio
import dataclasses

import pytest
from tests.unit.engine.audio.support import InMemorySynthesisCache, RecordingUsage

from motionile.engine.audio.cache_key import normalize_text, tts_cache_key
from motionile.engine.audio.models import SynthesisOptions, VoiceRef, WordTiming
from motionile.engine.audio.providers.base import ProviderUnavailableError
from motionile.engine.audio.providers.fake import FakeTTSProvider
from motionile.engine.audio.synthesis import CachedSynthesis, CachedSynthesizer, EmptyNarrationTextError

OPTIONS = SynthesisOptions(language="en", speed=1.0, stability=0.5, output_format="mp3_44100_128")
VOICE = VoiceRef("fake", "fake-voice-aria", "en")


def key(
    *,
    provider: str = "elevenlabs",
    model: str = "m1",
    voice: str = "v1",
    text: str = "Hello world",
    options: SynthesisOptions = OPTIONS,
) -> bytes:
    return tts_cache_key(provider, model, voice, text, options)


def test_key_is_a_sha256_digest() -> None:
    assert len(key()) == 32


def test_key_ignores_unicode_form_and_whitespace_layout() -> None:
    composed = "café  au\tlait\n"
    decomposed = "café au lait"

    assert key(text=composed) == key(text=decomposed)
    assert key(text="  a  b ") == key(text="a b")


def test_key_keeps_case_and_punctuation() -> None:
    assert key(text="Hello world") != key(text="hello world")
    assert key(text="Hello world.") != key(text="Hello world")


@pytest.mark.parametrize(
    "changed",
    [
        key(provider="openai"),
        key(model="m2"),
        key(voice="v2"),
        key(text="Another sentence"),
        key(options=dataclasses.replace(OPTIONS, speed=1.1)),
        key(options=dataclasses.replace(OPTIONS, stability=0.6)),
        key(options=dataclasses.replace(OPTIONS, language="hi")),
        key(options=dataclasses.replace(OPTIONS, output_format="mp3_22050_32")),
    ],
)
def test_every_field_changes_the_key(changed: bytes) -> None:
    assert changed != key()


def test_fields_are_length_prefixed() -> None:
    assert key(provider="ab", model="c") != key(provider="a", model="bc")
    assert key(voice="v1", text="2 x") != key(voice="v12", text=" x")


def test_settings_are_canonicalised() -> None:
    assert key(options=dataclasses.replace(OPTIONS, speed=1.00001)) == key()
    assert key(options=dataclasses.replace(OPTIONS, language=" EN ")) == key()
    assert key(options=dataclasses.replace(OPTIONS, output_format="MP3_44100_128")) == key()


def test_normalize_text_collapses_and_trims() -> None:
    text = "  one " + chr(10) + " two" + chr(0xA0) + "three  "
    assert normalize_text(text) == "one two three"


def build() -> tuple[CachedSynthesizer, FakeTTSProvider, InMemorySynthesisCache, RecordingUsage]:
    provider = FakeTTSProvider()
    cache = InMemorySynthesisCache()
    usage = RecordingUsage()
    return CachedSynthesizer(provider, cache, usage), provider, cache, usage


async def test_miss_synthesizes_stores_and_records_usage() -> None:
    synthesizer, provider, cache, usage = build()

    result = await synthesizer.synthesize("Hello  there world", VOICE, OPTIONS)

    assert not result.cache_hit
    assert provider.calls[0][0] == "Hello there world"
    assert len(cache.puts) == 1
    assert [(record.provider, record.model, record.characters, record.cost_micros_usd) for record in usage.records] == [
        ("fake", "fake-tts-1", len("Hello there world"), 0)
    ]
    assert result.duration_ms > 0
    assert [word.text for word in result.words] == ["Hello", "there", "world"]


async def test_hit_returns_identical_audio_without_provider_call_or_usage() -> None:
    synthesizer, provider, cache, usage = build()
    first = await synthesizer.synthesize("Hello there world", VOICE, OPTIONS)

    second = await synthesizer.synthesize("Hello   there\nworld", VOICE, OPTIONS)

    assert second.cache_hit
    assert second.audio == first.audio
    assert second.words == first.words
    assert second.duration_ms == first.duration_ms
    assert len(provider.calls) == 1
    assert len(usage.records) == 1
    assert cache.touched == [first.cache_key]


async def test_different_voice_or_settings_miss() -> None:
    synthesizer, provider, _, usage = build()

    await synthesizer.synthesize("Hello world", VOICE, OPTIONS)
    await synthesizer.synthesize("Hello world", VoiceRef("fake", "fake-voice-bram", "en"), OPTIONS)
    await synthesizer.synthesize("Hello world", VOICE, dataclasses.replace(OPTIONS, speed=1.2))

    assert len(provider.calls) == 3
    assert len(usage.records) == 3


async def test_race_loser_returns_the_winners_entry_and_still_records_usage() -> None:
    synthesizer, _, cache, usage = build()
    cache.winner = CachedSynthesis(
        cache_key=b"k" * 32,
        provider="fake",
        model="fake-tts-1",
        audio=b"winner-audio",
        content_type="audio/wav",
        duration_ms=1234,
        words=(WordTiming("Hello", 0, 500), WordTiming("world", 500, 1000)),
        characters=11,
    )

    result = await synthesizer.synthesize("Hello world", VOICE, OPTIONS)

    assert not result.cache_hit
    assert result.audio == b"winner-audio"
    assert result.duration_ms == 1234
    assert len(usage.records) == 1


async def test_concurrent_identical_requests_both_pay_and_converge_on_one_entry() -> None:
    provider = FakeTTSProvider()
    cache = InMemorySynthesisCache()
    usage = RecordingUsage()
    synthesizer = CachedSynthesizer(provider, cache, usage)

    first, second = await asyncio.gather(
        synthesizer.synthesize("Same text here", VOICE, OPTIONS),
        synthesizer.synthesize("Same text here", VOICE, OPTIONS),
    )

    assert first.audio == second.audio
    assert len(usage.records) == 2
    assert len(cache.entries) == 1


async def test_empty_text_is_refused_before_any_work() -> None:
    synthesizer, provider, cache, usage = build()

    with pytest.raises(EmptyNarrationTextError):
        await synthesizer.synthesize(" \n\t ", VOICE, OPTIONS)

    assert provider.calls == []
    assert cache.puts == []
    assert usage.records == []


async def test_provider_failure_stores_nothing_and_records_nothing() -> None:
    provider = FakeTTSProvider(failure=ProviderUnavailableError("down"))
    cache = InMemorySynthesisCache()
    usage = RecordingUsage()

    with pytest.raises(ProviderUnavailableError):
        await CachedSynthesizer(provider, cache, usage).synthesize("Hello world", VOICE, OPTIONS)

    assert cache.puts == []
    assert usage.records == []
