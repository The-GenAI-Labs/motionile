from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.ids import new_id
from motionile.modules.media.models import Asset, TtsCacheEntry

FRESH_ROWS = {"populate_existing": True}


@dataclass(frozen=True, slots=True)
class NewTtsEntry:
    content_hash: bytes
    provider: str
    model: str
    provider_voice_id: str
    characters: int
    duration_ms: int
    word_timings: list[dict[str, Any]]
    audio_asset_id: UUID
    last_used_at: datetime


@dataclass(frozen=True, slots=True)
class CachedRow:
    entry: TtsCacheEntry
    asset: Asset


class TtsCacheStore(Protocol):
    async def get(self, content_hash: bytes) -> CachedRow | None: ...

    async def insert(self, row: NewTtsEntry) -> TtsCacheEntry | None: ...

    async def touch(self, content_hash: bytes, at: datetime) -> None: ...

    async def delete_entry(self, entry_id: UUID) -> None: ...

    async def for_voice(self, provider: str, provider_voice_id: str, limit: int) -> list[CachedRow]: ...

    async def unused_since(self, before: datetime, limit: int) -> list[CachedRow]: ...


class SqlTtsCacheRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, content_hash: bytes) -> CachedRow | None:
        statement = (
            select(TtsCacheEntry, Asset)
            .join(Asset, Asset.id == TtsCacheEntry.audio_asset_id)
            .where(TtsCacheEntry.content_hash == content_hash)
            .execution_options(**FRESH_ROWS)
        )
        row = (await self.session.execute(statement)).first()
        return CachedRow(row[0], row[1]) if row is not None else None

    async def insert(self, row: NewTtsEntry) -> TtsCacheEntry | None:
        statement = (
            pg_insert(TtsCacheEntry)
            .values(
                id=new_id(),
                content_hash=row.content_hash,
                provider=row.provider,
                model=row.model,
                provider_voice_id=row.provider_voice_id,
                characters=row.characters,
                duration_ms=row.duration_ms,
                word_timings=row.word_timings,
                audio_asset_id=row.audio_asset_id,
                hit_count=0,
                last_used_at=row.last_used_at,
            )
            .on_conflict_do_nothing(index_elements=[TtsCacheEntry.content_hash])
            .returning(TtsCacheEntry)
            .execution_options(**FRESH_ROWS)
        )
        return await self.session.scalar(statement)

    async def touch(self, content_hash: bytes, at: datetime) -> None:
        await self.session.execute(
            update(TtsCacheEntry)
            .where(TtsCacheEntry.content_hash == content_hash)
            .values(hit_count=TtsCacheEntry.hit_count + 1, last_used_at=at)
        )

    async def delete_entry(self, entry_id: UUID) -> None:
        await self.session.execute(delete(TtsCacheEntry).where(TtsCacheEntry.id == entry_id))

    async def for_voice(self, provider: str, provider_voice_id: str, limit: int) -> list[CachedRow]:
        statement = (
            select(TtsCacheEntry, Asset)
            .join(Asset, Asset.id == TtsCacheEntry.audio_asset_id)
            .where(TtsCacheEntry.provider == provider, TtsCacheEntry.provider_voice_id == provider_voice_id)
            .order_by(TtsCacheEntry.id)
            .limit(limit)
            .execution_options(**FRESH_ROWS)
        )
        return [CachedRow(entry, asset) for entry, asset in (await self.session.execute(statement)).all()]

    async def unused_since(self, before: datetime, limit: int) -> list[CachedRow]:
        statement = (
            select(TtsCacheEntry, Asset)
            .join(Asset, Asset.id == TtsCacheEntry.audio_asset_id)
            .where(TtsCacheEntry.last_used_at < before)
            .order_by(TtsCacheEntry.last_used_at, TtsCacheEntry.id)
            .limit(limit)
            .execution_options(**FRESH_ROWS)
        )
        return [CachedRow(entry, asset) for entry, asset in (await self.session.execute(statement)).all()]
