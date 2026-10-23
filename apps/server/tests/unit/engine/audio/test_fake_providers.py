import dataclasses

import pytest

from motionile.engine.audio.models import CloneSample, SynthesisOptions, VoiceRef
from motionile.engine.audio.providers.base import ProviderNotFoundError, ProviderRejectedError, ProviderUnavailableError
from motionile.engine.audio.providers.fake import (
    BUILT_IN_VOICES,
    FakeTranscriber,
    FakeTranscriptMode,
    FakeTTSProvider,
    FakeVoiceService,
    fake_timeline,
)
from motionile.engine.audio.timing import is_monotonic
from motionile.engine.audio.voice_clone import consent_similarity
from motionile.engine.audio.wav import parse_wav

VOICE = VoiceRef("fake", "fake-voice-aria", "en")
OPTIONS = SynthesisOptions(language="en")
SENTENCE = "I confirm that this is my own voice and my words are river silver candle and planet"


async def test_same_input_gives_byte_identical_audio_and_timings() -> None:
    first = await FakeTTSProvider().synthesize("Every video begins with a question.", VOICE, OPTIONS)
    second = await FakeTTSProvider().synthesize("Every video begins with a question.", VOICE, OPTIONS)

    assert first.audio == second.audio
    assert first.words == second.words
    assert first.duration_ms == second.duration_ms


async def test_audio_is_a_wav_whose_duration_follows_the_text_length() -> None:
    short = await FakeTTSProvider().synthesize("Hi there", VOICE, OPTIONS)
    long = await FakeTTSProvider().synthesize("Hi there " + "and so on " * 20, VOICE, OPTIONS)

    info = parse_wav(short.audio)
    assert (info.sample_rate, info.channels) == (16000, 1)
    assert short.content_type == "audio/wav"
    assert info.duration_ms == short.duration_ms
    assert long.duration_ms > short.duration_ms * 5


async def test_word_timings_are_plausible_monotonic_and_inside_the_audio() -> None:
    text = "Photosynthesis converts light into chemical energy, quickly."

    result = await FakeTTSProvider().synthesize(text, VOICE, OPTIONS)

    assert [word.text for word in result.words] == text.split()
    assert is_monotonic(result.words)
    assert result.words[-1].end_ms <= result.duration_ms
    lengths = {word.text: word.end_ms - word.start_ms for word in result.words}
    assert lengths["Photosynthesis"] > lengths["into"]


async def test_speed_shortens_the_audio() -> None:
    normal = await FakeTTSProvider().synthesize("one two three four five", VOICE, OPTIONS)
    fast = await FakeTTSProvider().synthesize("one two three four five", VOICE, dataclasses.replace(OPTIONS, speed=2.0))

    assert fast.duration_ms < normal.duration_ms


async def test_voice_and_text_change_the_audio() -> None:
    base = await FakeTTSProvider().synthesize("hello world", VOICE, OPTIONS)
    other_voice = await FakeTTSProvider().synthesize("hello world", VoiceRef("fake", "fake-voice-bram", "en"), OPTIONS)
    other_text = await FakeTTSProvider().synthesize("hello there", VOICE, OPTIONS)

    assert base.audio != other_voice.audio
    assert base.audio != other_text.audio


async def test_silence_mode_has_the_same_timeline_without_tone() -> None:
    tone = await FakeTTSProvider().synthesize("hello world", VOICE, OPTIONS)
    silence = await FakeTTSProvider(tone=False).synthesize("hello world", VOICE, OPTIONS)

    info = parse_wav(silence.audio)
    assert silence.words == tone.words
    assert set(silence.audio[info.data_offset : info.data_offset + info.data_bytes]) == {0}
    assert any(tone.audio[parse_wav(tone.audio).data_offset :][: parse_wav(tone.audio).data_bytes])


async def test_usage_fields_and_call_recording() -> None:
    provider = FakeTTSProvider()

    result = await provider.synthesize("hello world", VOICE, OPTIONS)

    assert (result.characters, result.cost_micros_usd, result.model) == (11, 0, "fake-tts-1")
    assert provider.calls == [("hello world", VOICE, OPTIONS)]
    assert provider.returns_native_timestamps
    assert provider.name == "fake"


async def test_failures_can_be_injected_and_empty_text_is_rejected() -> None:
    with pytest.raises(ProviderUnavailableError):
        await FakeTTSProvider(failure=ProviderUnavailableError("down")).synthesize("hello", VOICE, OPTIONS)
    with pytest.raises(ProviderRejectedError):
        await FakeTTSProvider().synthesize("   ", VOICE, OPTIONS)


def test_timeline_starts_after_a_short_lead_and_is_gapped() -> None:
    timeline = fake_timeline(["a", "b"], 1.0)

    assert timeline[0].start_ms > 0
    assert timeline[1].start_ms > timeline[0].end_ms


async def test_transcriber_reads_back_what_the_fake_provider_said() -> None:
    audio = (await FakeTTSProvider().synthesize(SENTENCE, VOICE, OPTIONS)).audio

    transcript = await FakeTranscriber().transcribe(audio, "x.wav", "en")

    assert transcript.text == SENTENCE
    assert [word.text for word in transcript.words] == SENTENCE.split()
    assert is_monotonic(transcript.words)
    assert consent_similarity(SENTENCE, transcript.text) == 1.0


async def test_transcriber_derives_words_from_the_length_of_foreign_audio() -> None:
    transcript = await FakeTranscriber().transcribe(b"\x00" * 16_000, "x.mp3", None)

    assert len(transcript.words) >= 1
    assert transcript.words[-1].end_ms <= 1000


async def test_transcriber_modes() -> None:
    audio = (await FakeTTSProvider().synthesize(SENTENCE, VOICE, OPTIONS)).audio

    fixed = await FakeTranscriber(FakeTranscriptMode.FIXED, "exactly this text").transcribe(audio, "x.wav", "en")
    wrong = await FakeTranscriber(FakeTranscriptMode.WRONG).transcribe(audio, "x.wav", "en")
    empty = await FakeTranscriber(FakeTranscriptMode.EMPTY).transcribe(audio, "x.wav", "en")

    assert fixed.text == "exactly this text"
    assert len(wrong.words) == len(SENTENCE.split())
    assert consent_similarity(SENTENCE, wrong.text) < 0.3
    assert empty.words == ()


def test_fixed_mode_requires_a_transcript() -> None:
    with pytest.raises(ValueError, match="transcript"):
        FakeTranscriber(FakeTranscriptMode.FIXED)


async def test_transcriber_records_its_calls() -> None:
    transcriber = FakeTranscriber()

    await transcriber.transcribe(b"", "a.wav", "hi")

    assert transcriber.calls == [("a.wav", "hi")]


async def test_voice_service_lists_built_ins_and_clones_deterministically() -> None:
    service = FakeVoiceService()
    samples = [CloneSample("a.wav", b"one"), CloneSample("b.wav", b"two")]

    first = await service.clone("Mine", "en", samples, None)
    again = await FakeVoiceService().clone("Mine", "en", list(reversed(samples)), None)
    other = await service.clone("Mine", "en", [CloneSample("a.wav", b"different")], None)

    assert first == again
    assert first != other
    assert first.startswith("fake-clone-")
    listed = await service.list_voices()
    assert [voice.provider_voice_id for voice in listed][: len(BUILT_IN_VOICES)] == [
        voice.provider_voice_id for voice in BUILT_IN_VOICES
    ]
    assert {voice.provider_voice_id for voice in listed} >= {first, other}
    assert service.clone_calls[0] == ("Mine", "en", 2)


async def test_voice_service_tracks_deletion_and_reports_unknown_voices() -> None:
    service = FakeVoiceService()
    voice_id = await service.clone("Mine", "en", [CloneSample("a.wav", b"x")], None)

    await service.delete(voice_id)

    assert service.deleted == [voice_id]
    assert voice_id not in {voice.provider_voice_id for voice in await service.list_voices()}
    with pytest.raises(ProviderNotFoundError):
        await service.delete(voice_id)


async def test_voice_service_needs_samples() -> None:
    with pytest.raises(ProviderRejectedError):
        await FakeVoiceService().clone("Mine", "en", [], None)


async def test_text_source_overrides_what_the_audio_embeds() -> None:
    audio = (await FakeTTSProvider().synthesize(SENTENCE, VOICE, OPTIONS)).audio
    seen: list[bytes] = []

    async def source(received: bytes) -> str | None:
        seen.append(received)
        return "the hinted words"

    transcript = await FakeTranscriber(text_source=source).transcribe(audio, "x.wav", "en")

    assert transcript.text == "the hinted words"
    assert [word.text for word in transcript.words] == ["the", "hinted", "words"]
    assert seen == [audio]


async def test_text_source_without_a_hint_leaves_the_mode_in_charge() -> None:
    audio = (await FakeTTSProvider().synthesize(SENTENCE, VOICE, OPTIONS)).audio

    async def silent(_: bytes) -> str | None:
        return None

    embedded = await FakeTranscriber(text_source=silent).transcribe(audio, "x.wav", "en")
    wrong = await FakeTranscriber(FakeTranscriptMode.WRONG, text_source=silent).transcribe(audio, "x.wav", "en")

    assert embedded.text == SENTENCE
    assert consent_similarity(SENTENCE, wrong.text) < 0.3


async def test_text_source_wins_over_a_fixed_transcript() -> None:
    async def source(_: bytes) -> str | None:
        return "from the source"

    transcript = await FakeTranscriber(FakeTranscriptMode.FIXED, "from the mode", text_source=source).transcribe(
        b"", "x.wav", None
    )

    assert transcript.text == "from the source"
