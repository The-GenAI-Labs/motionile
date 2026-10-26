from collections.abc import AsyncGenerator, Collection, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.db import run_after_commit, run_after_rollback
from motionile.core.ids import new_id
from motionile.core.pagination import Cursor
from motionile.modules.media.exceptions import AssetKeyTakenError, AssetReferencedError
from motionile.modules.media.models import Asset, MusicTrack, Render, Rendition, TtsCacheEntry
from motionile.modules.media.music_repository import MusicFilter, MusicRow, NewMusicTrack
from motionile.modules.media.repository import NewAssetRow
from motionile.modules.media.tts_repository import CachedRow, NewTtsEntry

EPOCH = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def fake_session() -> AsyncSession:
    return AsyncSession()


@dataclass
class World:
    assets: dict[UUID, Asset] = field(default_factory=dict[UUID, Asset])
    entries: dict[UUID, TtsCacheEntry] = field(default_factory=dict[UUID, TtsCacheEntry])
    renders: dict[UUID, Render] = field(default_factory=dict[UUID, Render])
    renditions: dict[UUID, Rendition] = field(default_factory=dict[UUID, Rendition])
    tracks: dict[UUID, MusicTrack] = field(default_factory=dict[UUID, MusicTrack])
    referenced: set[UUID] = field(default_factory=set[UUID])
    transactions: int = 0
    rollbacks: int = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession]:
        session = fake_session()
        self.transactions += 1
        try:
            yield session
        except BaseException:
            self.rollbacks += 1
            await run_after_rollback(session)
            raise
        else:
            await run_after_commit(session)

    def asset_store(self, session: AsyncSession) -> "InMemoryAssetStore":
        del session
        return InMemoryAssetStore(self)

    def tts_store(self, session: AsyncSession) -> "InMemoryTtsCacheStore":
        del session
        return InMemoryTtsCacheStore(self)

    def render_store(self, session: AsyncSession) -> "InMemoryRenderStore":
        del session
        return InMemoryRenderStore(self)

    def music_store(self, session: AsyncSession) -> "InMemoryMusicStore":
        del session
        return InMemoryMusicStore(self)

    def add_asset(
        self,
        key: str,
        *,
        owner: UUID | None,
        kind: str = "video",
        status: str = "ready",
        content_type: str = "video/mp4",
    ) -> Asset:
        asset = Asset(
            id=new_id(),
            owner_user_id=owner,
            kind=kind,
            storage_key=key,
            content_type=content_type,
            size_bytes=3,
            sha256=bytes(32),
            duration_ms=None,
            width=None,
            height=None,
            status=status,
            metadata_={},
            created_at=EPOCH,
            updated_at=EPOCH,
        )
        self.assets[asset.id] = asset
        return asset


def add_render(world: World, owner: UUID, **overrides: Any) -> Render:
    composition = world.add_asset(f"media/u/{owner}/renders/x/composition.html", owner=owner, kind="html")
    values: dict[str, Any] = {
        "id": new_id(),
        "owner_user_id": owner,
        "source": "testbed",
        "status": "completed",
        "stage": None,
        "progress": 100,
        "options": {},
        "composition_asset_id": composition.id,
        "mixed_audio_asset_id": None,
        "subtitles_vtt_asset_id": None,
        "subtitles_srt_asset_id": None,
        "duration_ms": 5000,
        "validation_report": None,
        "stage_timings": {},
        "checkpoints": {},
        "error_code": None,
        "error_message": None,
        "cancel_requested_at": None,
        "started_at": EPOCH,
        "completed_at": EPOCH,
        "created_at": EPOCH,
        "updated_at": EPOCH,
        **overrides,
    }
    render = Render(**values)
    world.renders[render.id] = render
    return render


def add_rendition(world: World, render: Render, aspect: str, **overrides: Any) -> Rendition:
    slug = aspect.replace(":", "x")
    owner = render.owner_user_id
    video = world.add_asset(f"media/u/{owner}/renders/{render.id}/{slug}.mp4", owner=owner)
    values: dict[str, Any] = {
        "id": new_id(),
        "render_id": render.id,
        "aspect": aspect,
        "width": 1920,
        "height": 1080,
        "asset_id": video.id,
        "poster_webp_asset_id": world.add_asset(
            f"media/u/{owner}/renders/{render.id}/poster-{slug}.webp", owner=owner, kind="thumbnail"
        ).id,
        "poster_jpeg_asset_id": world.add_asset(
            f"media/u/{owner}/renders/{render.id}/poster-{slug}.jpg", owner=owner, kind="thumbnail"
        ).id,
        "status": "ready",
        "duration_ms": 5000,
        "burned_in_subtitles": False,
        "created_at": EPOCH,
        "updated_at": EPOCH,
        **overrides,
    }
    rendition = Rendition(**values)
    world.renditions[rendition.id] = rendition
    return rendition


class InMemoryAssetStore:
    def __init__(self, world: World) -> None:
        self._world = world

    async def insert_pending(self, row: NewAssetRow) -> Asset:
        if any(asset.storage_key == row.storage_key for asset in self._world.assets.values()):
            raise AssetKeyTakenError
        asset = Asset(
            id=new_id(),
            owner_user_id=row.owner_user_id,
            kind=row.kind,
            storage_key=row.storage_key,
            content_type=row.content_type,
            size_bytes=0,
            sha256=None,
            duration_ms=row.duration_ms,
            width=row.width,
            height=row.height,
            status="pending",
            metadata_=dict(row.metadata),
            created_at=EPOCH,
            updated_at=EPOCH,
        )
        self._world.assets[asset.id] = asset
        return asset

    async def mark_ready(self, asset_id: UUID, *, sha256: bytes, size_bytes: int) -> Asset:
        asset = self._world.assets[asset_id]
        asset.status = "ready"
        asset.sha256 = sha256
        asset.size_bytes = size_bytes
        return asset

    async def get(self, owner_user_id: UUID | None, asset_id: UUID) -> Asset | None:
        asset = self._world.assets.get(asset_id)
        return asset if asset is not None and asset.owner_user_id == owner_user_id else None

    async def get_by_key(self, owner_user_id: UUID | None, storage_key: str) -> Asset | None:
        for asset in self._world.assets.values():
            if asset.storage_key == storage_key and asset.owner_user_id == owner_user_id:
                return asset
        return None

    async def delete(self, owner_user_id: UUID | None, asset_id: UUID) -> bool:
        asset = await self.get(owner_user_id, asset_id)
        if asset is None:
            return False
        if asset_id in self._world.referenced:
            raise AssetReferencedError
        del self._world.assets[asset_id]
        return True

    async def delete_by_prefix(self, owner_user_id: UUID | None, prefix: str) -> list[str]:
        matching = [
            asset
            for asset in self._world.assets.values()
            if asset.storage_key.startswith(prefix) and asset.owner_user_id == owner_user_id
        ]
        if any(asset.id in self._world.referenced for asset in matching):
            raise AssetReferencedError
        for asset in matching:
            del self._world.assets[asset.id]
        return [asset.storage_key for asset in matching]


class InMemoryTtsCacheStore:
    def __init__(self, world: World) -> None:
        self._world = world

    def _row(self, entry: TtsCacheEntry) -> CachedRow:
        return CachedRow(entry, self._world.assets[entry.audio_asset_id])

    async def get(self, content_hash: bytes) -> CachedRow | None:
        for entry in self._world.entries.values():
            if entry.content_hash == content_hash:
                return self._row(entry)
        return None

    async def insert(self, row: NewTtsEntry) -> TtsCacheEntry | None:
        if any(entry.content_hash == row.content_hash for entry in self._world.entries.values()):
            return None
        entry = TtsCacheEntry(
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
            created_at=EPOCH,
            updated_at=EPOCH,
        )
        self._world.entries[entry.id] = entry
        self._world.referenced.add(row.audio_asset_id)
        return entry

    async def touch(self, content_hash: bytes, at: datetime) -> None:
        for entry in self._world.entries.values():
            if entry.content_hash == content_hash:
                entry.hit_count += 1
                entry.last_used_at = at

    async def delete_entry(self, entry_id: UUID) -> None:
        entry = self._world.entries.pop(entry_id, None)
        if entry is not None:
            self._world.referenced.discard(entry.audio_asset_id)

    async def for_voice(self, provider: str, provider_voice_id: str, limit: int) -> list[CachedRow]:
        matching = [
            entry
            for entry in self._world.entries.values()
            if entry.provider == provider and entry.provider_voice_id == provider_voice_id
        ]
        return [self._row(entry) for entry in matching[:limit]]

    async def unused_since(self, before: datetime, limit: int) -> list[CachedRow]:
        stale = sorted(
            (entry for entry in self._world.entries.values() if entry.last_used_at < before),
            key=lambda entry: entry.last_used_at,
        )
        return [self._row(entry) for entry in stale[:limit]]


class InMemoryRenderStore:
    def __init__(self, world: World) -> None:
        self._world = world

    async def get_render(self, owner_user_id: UUID, render_id: UUID) -> Render | None:
        render = self._world.renders.get(render_id)
        return render if render is not None and render.owner_user_id == owner_user_id else None

    async def renditions(self, render_id: UUID) -> list[Rendition]:
        return [item for item in self._world.renditions.values() if item.render_id == render_id]

    async def assets_by_ids(self, owner_user_id: UUID, asset_ids: Collection[UUID]) -> dict[UUID, Asset]:
        return {
            asset_id: self._world.assets[asset_id]
            for asset_id in asset_ids
            if asset_id in self._world.assets and self._world.assets[asset_id].owner_user_id == owner_user_id
        }

    async def music_track(self, track_id: UUID) -> MusicTrack | None:
        return self._world.tracks.get(track_id)

    async def render_ids_of(self, owner_user_id: UUID) -> list[UUID]:
        return [render.id for render in self._world.renders.values() if render.owner_user_id == owner_user_id]

    async def delete_render(self, owner_user_id: UUID, render_id: UUID) -> bool:
        render = self._world.renders.get(render_id)
        if render is None or render.owner_user_id != owner_user_id:
            return False
        del self._world.renders[render_id]
        for rendition_id in [item.id for item in self._world.renditions.values() if item.render_id == render_id]:
            del self._world.renditions[rendition_id]
        return True


class InMemoryMusicStore:
    def __init__(self, world: World) -> None:
        self._world = world

    def _row(self, track: MusicTrack) -> MusicRow:
        return MusicRow(track, self._world.assets[track.audio_asset_id].storage_key)

    async def insert(self, row: NewMusicTrack, storage_key: str) -> MusicRow:
        del storage_key
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
            created_at=EPOCH,
            updated_at=EPOCH,
        )
        self._world.tracks[track.id] = track
        return self._row(track)

    async def get(self, track_id: UUID) -> MusicRow | None:
        track = self._world.tracks.get(track_id)
        return self._row(track) if track is not None else None

    async def update(self, track_id: UUID, values: Mapping[str, Any]) -> MusicRow | None:
        track = self._world.tracks.get(track_id)
        if track is None:
            return None
        for name, value in values.items():
            setattr(track, name, value)
        return self._row(track)

    async def page(self, music_filter: MusicFilter, cursor: Cursor | None, limit: int) -> list[MusicRow]:
        del cursor
        tracks = [
            track
            for track in self._world.tracks.values()
            if (music_filter.mood is None or track.mood == music_filter.mood)
            and (music_filter.active is None or track.is_active == music_filter.active)
        ]
        return [self._row(track) for track in tracks[: limit + 1]]
