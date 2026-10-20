from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.pagination import Cursor, keyset_page
from motionile.modules.media.models import Asset, MusicTrack

FRESH_ROWS = {"populate_existing": True}


@dataclass(frozen=True, slots=True)
class NewMusicTrack:
    id: UUID
    title: str
    audio_asset_id: UUID
    mood: str
    bpm: int | None
    duration_ms: int
    license_name: str
    license_url: str
    attribution_text: str | None
    is_active: bool
    created_by_user_id: UUID | None


@dataclass(frozen=True, slots=True)
class MusicFilter:
    mood: str | None = None
    active: bool | None = None


@dataclass(frozen=True, slots=True)
class MusicRow:
    track: MusicTrack
    storage_key: str


class MusicStore(Protocol):
    async def insert(self, row: NewMusicTrack, storage_key: str) -> MusicRow: ...

    async def get(self, track_id: UUID) -> MusicRow | None: ...

    async def update(self, track_id: UUID, values: Mapping[str, Any]) -> MusicRow | None: ...

    async def page(self, music_filter: MusicFilter, cursor: Cursor | None, limit: int) -> list[MusicRow]: ...


class SqlMusicRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def insert(self, row: NewMusicTrack, storage_key: str) -> MusicRow:
        track = MusicTrack(
            id=row.id,
            title=row.title,
            audio_asset_id=row.audio_asset_id,
            mood=row.mood,
            bpm=row.bpm,
            duration_ms=row.duration_ms,
            license_name=row.license_name,
            license_url=row.license_url,
            attribution_text=row.attribution_text,
            is_active=row.is_active,
            created_by_user_id=row.created_by_user_id,
        )
        self.session.add(track)
        await self.session.flush()
        await self.session.refresh(track)
        return MusicRow(track, storage_key)

    async def get(self, track_id: UUID) -> MusicRow | None:
        statement = (
            select(MusicTrack, Asset.storage_key)
            .join(Asset, Asset.id == MusicTrack.audio_asset_id)
            .where(MusicTrack.id == track_id)
            .execution_options(**FRESH_ROWS)
        )
        found = (await self.session.execute(statement)).first()
        return MusicRow(found[0], found[1]) if found is not None else None

    async def update(self, track_id: UUID, values: Mapping[str, Any]) -> MusicRow | None:
        await self.session.execute(update(MusicTrack).where(MusicTrack.id == track_id).values(**values))
        return await self.get(track_id)

    async def page(self, music_filter: MusicFilter, cursor: Cursor | None, limit: int) -> list[MusicRow]:
        statement = select(MusicTrack, Asset.storage_key).join(Asset, Asset.id == MusicTrack.audio_asset_id)
        if music_filter.mood is not None:
            statement = statement.where(MusicTrack.mood == music_filter.mood)
        if music_filter.active is not None:
            statement = statement.where(MusicTrack.is_active.is_(music_filter.active))
        paged = keyset_page(
            statement, created_at=MusicTrack.created_at, id_=MusicTrack.id, cursor=cursor, limit=limit
        ).execution_options(**FRESH_ROWS)
        return [MusicRow(track, key) for track, key in (await self.session.execute(paged)).all()]
