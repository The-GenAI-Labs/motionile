from dataclasses import dataclass, field
from typing import Protocol

from motionile.engine.audio.cache_key import normalize_text, tts_cache_key
from motionile.engine.audio.models import SynthesisOptions, SynthesisResult, VoiceRef, WordTiming
from motionile.engine.audio.providers.base import TTSProvider


class EmptyNarrationTextError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CachedSynthesis:
    cache_key: bytes
    provider: str
    model: str
    audio: bytes = field(repr=False)
    content_type: str
    duration_ms: int
    words: tuple[WordTiming, ...]
    characters: int


@dataclass(frozen=True, slots=True)
class NewCacheEntry:
    cache_key: bytes
    provider: str
    voice: VoiceRef
    result: SynthesisResult


@dataclass(frozen=True, slots=True)
class SynthesisUsage:
    provider: str
    model: str
    characters: int
    cost_micros_usd: int


@dataclass(frozen=True, slots=True)
class NarratedAudio:
    cache_key: bytes
    provider: str
    model: str
    audio: bytes = field(repr=False)
    content_type: str
    duration_ms: int
    words: tuple[WordTiming, ...]
    characters: int
    cache_hit: bool


class SynthesisCache(Protocol):
    async def get(self, cache_key: bytes) -> CachedSynthesis | None: ...

    async def put(self, entry: NewCacheEntry) -> CachedSynthesis: ...

    async def touch(self, cache_key: bytes) -> None: ...


class UsageSink(Protocol):
    async def record(self, usage: SynthesisUsage) -> None: ...


def narrated_from(entry: CachedSynthesis, *, cache_hit: bool) -> NarratedAudio:
    return NarratedAudio(
        cache_key=entry.cache_key,
        provider=entry.provider,
        model=entry.model,
        audio=entry.audio,
        content_type=entry.content_type,
        duration_ms=entry.duration_ms,
        words=entry.words,
        characters=entry.characters,
        cache_hit=cache_hit,
    )


class CachedSynthesizer:
    def __init__(self, provider: TTSProvider, cache: SynthesisCache, usage: UsageSink) -> None:
        self._provider = provider
        self._cache = cache
        self._usage = usage

    async def synthesize(self, text: str, voice: VoiceRef, options: SynthesisOptions) -> NarratedAudio:
        normalized = normalize_text(text)
        if not normalized:
            raise EmptyNarrationTextError("the narration text is empty")
        cache_key = tts_cache_key(
            self._provider.name, self._provider.model, voice.provider_voice_id, normalized, options
        )
        cached = await self._cache.get(cache_key)
        if cached is not None:
            await self._cache.touch(cache_key)
            return narrated_from(cached, cache_hit=True)
        result = await self._provider.synthesize(normalized, voice, options)
        stored = await self._cache.put(NewCacheEntry(cache_key, self._provider.name, voice, result))
        await self._usage.record(
            SynthesisUsage(self._provider.name, result.model, result.characters, result.cost_micros_usd)
        )
        return narrated_from(stored, cache_hit=False)
