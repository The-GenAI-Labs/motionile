import hashlib
import math
from array import array
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from motionile.engine.audio.models import (
    CloneSample,
    ProviderVoice,
    SynthesisOptions,
    SynthesisResult,
    Transcript,
    VoiceRef,
    WordTiming,
)
from motionile.engine.audio.providers.base import ProviderError, ProviderNotFoundError, ProviderRejectedError
from motionile.engine.audio.wav import WavError, build_wav, parse_wav

PROVIDER_NAME = "fake"
MODEL_NAME = "fake-tts-1"
SAMPLE_RATE = 16_000
LEAD_MS = 100
TRAIL_MS = 150
WORD_BASE_MS = 120
WORD_PER_CHARACTER_MS = 55
WORD_GAP_MS = 70
MIN_SPEED = 0.25
FADE_MS = 10
AMPLITUDE = 0.25
BASE_FREQUENCY_HZ = 160
VOICE_FREQUENCY_SPREAD = 120
WORD_FREQUENCY_SPREAD = 80
PCM_PEAK = 32767
BYTES_PER_MS_FALLBACK = 16
DERIVED_WORD_MS = 400
WRONG_WORDS = (
    "anchor",
    "blanket",
    "cactus",
    "dolphin",
    "engine",
    "feather",
    "glacier",
    "hammer",
    "island",
    "jacket",
    "kettle",
    "lemon",
)
BUILT_IN_VOICES = (
    ProviderVoice("fake-voice-aria", "Aria", "en", {"gender": "female", "accent": "neutral"}, None),
    ProviderVoice("fake-voice-bram", "Bram", "en", {"gender": "male", "accent": "neutral"}, None),
    ProviderVoice("fake-voice-esha", "Esha", "hi", {"gender": "female", "accent": "neutral"}, None),
    ProviderVoice("fake-voice-ravi", "Ravi", "hi", {"gender": "male", "accent": "neutral"}, None),
)


class FakeTranscriptMode(StrEnum):
    EMBEDDED = "embedded"
    FIXED = "fixed"
    WRONG = "wrong"
    EMPTY = "empty"


def digest_byte(value: str) -> int:
    return hashlib.sha256(value.encode("utf-8")).digest()[0]


def word_duration_ms(word: str, speed: float) -> int:
    core = sum(1 for character in word if character.isalnum()) or 1
    return round((WORD_BASE_MS + WORD_PER_CHARACTER_MS * core) / max(speed, MIN_SPEED))


def fake_timeline(words: Sequence[str], speed: float) -> tuple[WordTiming, ...]:
    gap = round(WORD_GAP_MS / max(speed, MIN_SPEED))
    cursor = LEAD_MS
    timings: list[WordTiming] = []
    for word in words:
        end = cursor + word_duration_ms(word, speed)
        timings.append(WordTiming(word, cursor, end))
        cursor = end + gap
    return tuple(timings)


def timeline_length_ms(timings: Sequence[WordTiming]) -> int:
    return (timings[-1].end_ms if timings else LEAD_MS) + TRAIL_MS


def tone_samples(frequency: float, length_ms: int) -> array[int]:
    count = length_ms * SAMPLE_RATE // 1000
    fade = FADE_MS * SAMPLE_RATE // 1000
    samples = array("h")
    for index in range(count):
        envelope = min(1.0, (index + 1) / fade, (count - index) / fade)
        value = AMPLITUDE * envelope * math.sin(2 * math.pi * frequency * index / SAMPLE_RATE)
        samples.append(round(value * PCM_PEAK))
    return samples


def render_pcm(timings: Sequence[WordTiming], voice_id: str, *, tone: bool) -> bytes:
    total = timeline_length_ms(timings) * SAMPLE_RATE // 1000
    samples = array("h", bytes(total * 2))
    if tone:
        base = BASE_FREQUENCY_HZ + digest_byte(voice_id) % VOICE_FREQUENCY_SPREAD
        for timing in timings:
            frequency = base + digest_byte(timing.text) % WORD_FREQUENCY_SPREAD
            start = timing.start_ms * SAMPLE_RATE // 1000
            segment = tone_samples(frequency, timing.end_ms - timing.start_ms)
            samples[start : start + len(segment)] = segment
    return samples.tobytes()


class FakeTTSProvider:
    name = PROVIDER_NAME
    model = MODEL_NAME
    returns_native_timestamps = True

    def __init__(self, *, tone: bool = True, failure: ProviderError | None = None) -> None:
        self.tone = tone
        self.failure = failure
        self.calls: list[tuple[str, VoiceRef, SynthesisOptions]] = []

    async def synthesize(self, text: str, voice: VoiceRef, options: SynthesisOptions) -> SynthesisResult:
        self.calls.append((text, voice, options))
        if self.failure is not None:
            raise self.failure
        words = text.split()
        if not words:
            raise ProviderRejectedError("the text has no words", reason="empty_text")
        timings = fake_timeline(words, options.speed)
        pcm = render_pcm(timings, voice.provider_voice_id, tone=self.tone)
        audio = build_wav(pcm, sample_rate=SAMPLE_RATE, embedded_text=text)
        return SynthesisResult(
            audio=audio,
            content_type="audio/wav",
            duration_ms=parse_wav(audio).duration_ms,
            words=timings,
            characters=len(text),
            cost_micros_usd=0,
            model=MODEL_NAME,
        )


def wrong_word(word: str) -> str:
    index = digest_byte(word) % len(WRONG_WORDS)
    candidate = WRONG_WORDS[index]
    return candidate if candidate != word else WRONG_WORDS[(index + 1) % len(WRONG_WORDS)]


@dataclass(frozen=True, slots=True)
class AudioFacts:
    duration_ms: int
    text: str | None


def audio_facts(audio: bytes) -> AudioFacts:
    try:
        info = parse_wav(audio)
    except WavError:
        return AudioFacts(max(len(audio) // BYTES_PER_MS_FALLBACK, 1), None)
    return AudioFacts(info.duration_ms, info.embedded_text)


def evenly_timed(words: Sequence[str], duration_ms: int) -> tuple[WordTiming, ...]:
    if not words:
        return ()
    weights = [max(len(word), 1) for word in words]
    total = sum(weights)
    timings: list[WordTiming] = []
    consumed = 0
    for word, weight in zip(words, weights, strict=True):
        start = duration_ms * consumed // total
        consumed += weight
        timings.append(WordTiming(word, start, duration_ms * consumed // total))
    return tuple(timings)


type TranscriptTextSource = Callable[[bytes], Awaitable[str | None]]


class FakeTranscriber:
    name = PROVIDER_NAME

    def __init__(
        self,
        mode: FakeTranscriptMode = FakeTranscriptMode.EMBEDDED,
        fixed_text: str | None = None,
        text_source: TranscriptTextSource | None = None,
    ) -> None:
        if mode is FakeTranscriptMode.FIXED and fixed_text is None:
            raise ValueError("fixed mode needs a transcript")
        self.mode = mode
        self.fixed_text = fixed_text
        self.text_source = text_source
        self.calls: list[tuple[str, str | None]] = []

    def words_for(self, facts: AudioFacts) -> list[str]:
        if self.mode is FakeTranscriptMode.EMPTY:
            return []
        if self.mode is FakeTranscriptMode.FIXED:
            return (self.fixed_text or "").split()
        spoken = (
            facts.text.split() if facts.text is not None else ["word"] * max(facts.duration_ms // DERIVED_WORD_MS, 1)
        )
        if self.mode is FakeTranscriptMode.WRONG:
            return [wrong_word(word) for word in spoken]
        return spoken

    async def transcribe(self, audio: bytes, filename: str, language: str | None) -> Transcript:
        self.calls.append((filename, language))
        facts = audio_facts(audio)
        hinted = await self.text_source(audio) if self.text_source is not None else None
        words = hinted.split() if hinted is not None else self.words_for(facts)
        return Transcript(text=" ".join(words), words=evenly_timed(words, facts.duration_ms))


class FakeVoiceService:
    def __init__(self) -> None:
        self.cloned: dict[str, ProviderVoice] = {}
        self.deleted: list[str] = []
        self.clone_calls: list[tuple[str, str | None, int]] = []

    async def list_voices(self) -> Sequence[ProviderVoice]:
        return [*BUILT_IN_VOICES, *self.cloned.values()]

    async def clone(
        self, name: str, language: str | None, samples: Sequence[CloneSample], description: str | None
    ) -> str:
        if not samples:
            raise ProviderRejectedError("at least one sample is required", reason="invalid_samples")
        self.clone_calls.append((name, language, len(samples)))
        fingerprint = hashlib.sha256()
        fingerprint.update(f"{name}\x00{language or ''}\x00{description or ''}".encode())
        for digest in sorted(hashlib.sha256(sample.content).hexdigest() for sample in samples):
            fingerprint.update(digest.encode())
        voice_id = f"fake-clone-{fingerprint.hexdigest()[:16]}"
        self.cloned[voice_id] = ProviderVoice(voice_id, name, language, {"category": "cloned"}, None)
        return voice_id

    async def delete(self, provider_voice_id: str) -> None:
        if provider_voice_id not in self.cloned:
            raise ProviderNotFoundError("the voice does not exist", status_code=404, reason="voice_not_found")
        del self.cloned[provider_voice_id]
        self.deleted.append(provider_voice_id)
