from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import Clock
from motionile.core.errors import ServiceUnavailableError
from motionile.core.storage.base import ObjectNotFoundError
from motionile.engine.audio.models import WordTiming
from motionile.engine.audio.synthesis import CachedSynthesis, NewCacheEntry, SynthesisUsage
from motionile.modules.credits import UsageEntry, record_usage
from motionile.modules.media.assets import AssetService, AssetSpec, asset_view
from motionile.modules.media.domain import AssetKind
from motionile.modules.media.exceptions import AssetKeyExistsError
from motionile.modules.media.keys import tts_key
from motionile.modules.media.models import TtsCacheEntry
from motionile.modules.media.ports import Transaction
from motionile.modules.media.tts_repository import CachedRow, NewTtsEntry, SqlTtsCacheRepository, TtsCacheStore

logger = structlog.get_logger(__name__)

type TtsStoreFactory = Callable[[AsyncSession], TtsCacheStore]

USAGE_STAGE = "tts"
AUDIO_EXTENSIONS = {
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/ogg": "ogg",
    "audio/aac": "aac",
    "audio/flac": "flac",
}
FALLBACK_EXTENSION = "bin"
PUT_ATTEMPTS = 3
EVICT_BATCH_SIZE = 200


class TtsCacheUnavailableError(ServiceUnavailableError):
    default_code = "tts_cache_unavailable"
    title = "Speech cache unavailable"


class LostCacheRaceError(Exception):
    pass


def words_to_json(words: tuple[WordTiming, ...]) -> list[dict[str, Any]]:
    return [{"text": word.text, "start_ms": word.start_ms, "end_ms": word.end_ms} for word in words]


def words_from_json(payload: list[dict[str, Any]]) -> tuple[WordTiming, ...]:
    return tuple(WordTiming(str(item["text"]), int(item["start_ms"]), int(item["end_ms"])) for item in payload)


def cached_synthesis(entry: TtsCacheEntry, content_type: str, audio: bytes) -> CachedSynthesis:
    return CachedSynthesis(
        cache_key=entry.content_hash,
        provider=entry.provider,
        model=entry.model,
        audio=audio,
        content_type=content_type,
        duration_ms=entry.duration_ms,
        words=words_from_json(entry.word_timings),
        characters=entry.characters,
    )


class SqlSynthesisCache:
    def __init__(
        self,
        transaction: Transaction,
        assets: AssetService,
        clock: Clock,
        store_factory: TtsStoreFactory = SqlTtsCacheRepository,
    ) -> None:
        self._transaction = transaction
        self._assets = assets
        self._clock = clock
        self._store_factory = store_factory

    async def get(self, cache_key: bytes) -> CachedSynthesis | None:
        async with self._transaction() as session:
            row = await self._store_factory(session).get(cache_key)
        if row is None:
            return None
        try:
            audio = await self._assets.read_bytes(asset_view(row.asset))
        except ObjectNotFoundError:
            logger.warning("media.tts_cache_object_missing", entry_id=str(row.entry.id))
            await self._evict(row)
            return None
        return cached_synthesis(row.entry, row.asset.content_type, audio)

    async def put(self, entry: NewCacheEntry) -> CachedSynthesis:
        for _ in range(PUT_ATTEMPTS):
            try:
                return await self._insert(entry)
            except (AssetKeyExistsError, LostCacheRaceError):
                winner = await self.get(entry.cache_key)
                if winner is not None:
                    return winner
        raise TtsCacheUnavailableError

    async def touch(self, cache_key: bytes) -> None:
        async with self._transaction() as session:
            await self._store_factory(session).touch(cache_key, self._clock.now())

    async def _insert(self, entry: NewCacheEntry) -> CachedSynthesis:
        result = entry.result
        extension = AUDIO_EXTENSIONS.get(result.content_type, FALLBACK_EXTENSION)
        spec = AssetSpec(
            key=tts_key(entry.cache_key.hex(), extension),
            kind=AssetKind.AUDIO,
            content_type=result.content_type,
            duration_ms=result.duration_ms,
            metadata={"provider": entry.provider, "model": result.model},
        )
        async with self._transaction() as session:
            asset = await self._assets.store_bytes(session, result.audio, spec)
            inserted = await self._store_factory(session).insert(
                NewTtsEntry(
                    content_hash=entry.cache_key,
                    provider=entry.provider,
                    model=result.model,
                    provider_voice_id=entry.voice.provider_voice_id,
                    characters=result.characters,
                    duration_ms=result.duration_ms,
                    word_timings=words_to_json(result.words),
                    audio_asset_id=asset.id,
                    last_used_at=self._clock.now(),
                )
            )
            if inserted is None:
                raise LostCacheRaceError
        return cached_synthesis(inserted, result.content_type, result.audio)

    async def evict_voice(self, provider: str, provider_voice_id: str) -> int:
        evicted = 0
        while True:
            async with self._transaction() as session:
                rows = await self._store_factory(session).for_voice(provider, provider_voice_id, EVICT_BATCH_SIZE)
                await self._remove(session, rows)
            evicted += len(rows)
            if len(rows) < EVICT_BATCH_SIZE:
                return evicted

    async def evict_unused(self, before: datetime) -> int:
        evicted = 0
        while True:
            async with self._transaction() as session:
                rows = await self._store_factory(session).unused_since(before, EVICT_BATCH_SIZE)
                await self._remove(session, rows)
            evicted += len(rows)
            if len(rows) < EVICT_BATCH_SIZE:
                return evicted

    async def _evict(self, row: CachedRow) -> None:
        async with self._transaction() as session:
            await self._remove(session, [row])

    async def _remove(self, session: AsyncSession, rows: list[CachedRow]) -> None:
        store = self._store_factory(session)
        for row in rows:
            await store.delete_entry(row.entry.id)
            await self._assets.delete(session, None, row.asset.id)


class SpeechUsageSink:
    def __init__(self, transaction: Transaction, user_id: UUID, job_id: UUID | None = None) -> None:
        self._transaction = transaction
        self._user_id = user_id
        self._job_id = job_id

    async def record(self, usage: SynthesisUsage) -> None:
        async with self._transaction() as session:
            await record_usage(
                session,
                UsageEntry(
                    user_id=self._user_id,
                    stage=USAGE_STAGE,
                    provider=usage.provider,
                    key=f"{USAGE_STAGE}:{usage.cache_key.hex()}:{usage.nonce}",
                    model=usage.model,
                    audio_characters=usage.characters,
                    cost_micros_usd=usage.cost_micros_usd,
                    job_id=self._job_id,
                ),
            )
