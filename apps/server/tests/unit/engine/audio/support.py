import asyncio
import ipaddress
from dataclasses import dataclass, field

import httpx
import orjson

from motionile.core.config import OutboundHttpSettings
from motionile.core.http.safe_client import IPAddress, SafeHttpClient
from motionile.engine.audio.models import Transcript, WordTiming
from motionile.engine.audio.providers.transport import RetryPolicy
from motionile.engine.audio.synthesis import CachedSynthesis, NewCacheEntry, SynthesisUsage


async def public_dns(_host: str, _port: int) -> list[IPAddress]:
    return [ipaddress.ip_address("104.18.0.1")]


@dataclass
class Script:
    responses: list[httpx.Response | Exception]
    requests: list[httpx.Request] = field(default_factory=list[httpx.Request])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    @property
    def last_json(self) -> dict[str, object]:
        body: dict[str, object] = orjson.loads(self.last.content)
        return body


@dataclass
class Sleeps:
    delays: list[float] = field(default_factory=list[float])

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


FAST_RETRY = RetryPolicy(attempts=3, base_delay_seconds=0.1, max_delay_seconds=0.4, retry_after_cap_seconds=1.0)


def json_response(payload: object, status: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, content=orjson.dumps(payload), headers=headers)


def safe_client(script: Script, *, allowed_hosts: tuple[str, ...] | None = None) -> SafeHttpClient:
    return SafeHttpClient(
        OutboundHttpSettings(), resolver=public_dns, allowed_hosts=allowed_hosts, transport=httpx.MockTransport(script)
    )


class StaticMeter:
    def __init__(self, duration_ms: int) -> None:
        self.duration_ms = duration_ms
        self.calls = 0
        self.sizes: list[int] = []

    async def measure_ms(self, audio: bytes) -> int:
        self.calls += 1
        self.sizes.append(len(audio))
        return self.duration_ms


class ScriptedTranscriber:
    name = "scripted"

    def __init__(self, words: list[WordTiming]) -> None:
        self.words = words
        self.calls: list[tuple[str, str | None]] = []
        self.sizes: list[int] = []

    async def transcribe(self, audio: bytes, filename: str, language: str | None) -> Transcript:
        self.calls.append((filename, language))
        self.sizes.append(len(audio))
        return Transcript(" ".join(word.text for word in self.words), tuple(self.words))


class InMemorySynthesisCache:
    def __init__(self) -> None:
        self.entries: dict[bytes, CachedSynthesis] = {}
        self.touched: list[bytes] = []
        self.puts: list[NewCacheEntry] = []
        self.winner: CachedSynthesis | None = None
        self.put_failure: Exception | None = None

    async def get(self, cache_key: bytes) -> CachedSynthesis | None:
        found = self.entries.get(cache_key)
        await asyncio.sleep(0)
        return found

    async def put(self, entry: NewCacheEntry) -> CachedSynthesis:
        self.puts.append(entry)
        if self.put_failure is not None:
            raise self.put_failure
        if self.winner is not None:
            self.entries[entry.cache_key] = self.winner
            return self.winner
        existing = self.entries.get(entry.cache_key)
        if existing is not None:
            return existing
        cached = CachedSynthesis(
            cache_key=entry.cache_key,
            provider=entry.provider,
            model=entry.result.model,
            audio=entry.result.audio,
            content_type=entry.result.content_type,
            duration_ms=entry.result.duration_ms,
            words=entry.result.words,
            characters=entry.result.characters,
        )
        self.entries[entry.cache_key] = cached
        return cached

    async def touch(self, cache_key: bytes) -> None:
        self.touched.append(cache_key)


class RecordingUsage:
    def __init__(self) -> None:
        self.records: list[SynthesisUsage] = []

    async def record(self, usage: SynthesisUsage) -> None:
        self.records.append(usage)
