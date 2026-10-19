from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class WordTiming:
    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True, slots=True)
class VoiceRef:
    provider: str
    provider_voice_id: str
    language: str | None = None


@dataclass(frozen=True, slots=True)
class SynthesisOptions:
    language: str
    speed: float = 1.0
    stability: float = 0.5
    output_format: str = "mp3_44100_128"


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    audio: bytes = field(repr=False)
    content_type: str
    duration_ms: int
    words: tuple[WordTiming, ...]
    characters: int
    cost_micros_usd: int
    model: str


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    words: tuple[WordTiming, ...]


@dataclass(frozen=True, slots=True)
class ProviderVoice:
    provider_voice_id: str
    name: str
    language: str | None
    labels: Mapping[str, str]
    preview_url: str | None


@dataclass(frozen=True, slots=True)
class CloneSample:
    filename: str
    content: bytes = field(repr=False)
    content_type: str = "audio/wav"
