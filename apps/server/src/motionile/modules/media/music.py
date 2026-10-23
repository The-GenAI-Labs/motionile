from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.ids import new_id
from motionile.core.pagination import Cursor
from motionile.core.storage.base import Storage
from motionile.modules.audit import ActorType, AuditContext, AuditEvent
from motionile.modules.audit import record as record_audit
from motionile.modules.media.assets import AssetService, AssetSpec
from motionile.modules.media.domain import AssetKind
from motionile.modules.media.exceptions import (
    MusicTrackNotFoundError,
    MusicTrackUnavailableError,
    MusicUpdateEmptyError,
)
from motionile.modules.media.keys import music_key
from motionile.modules.media.music_audio import MUSIC_CONTENT_TYPE, MUSIC_EXTENSION, MusicAudioProcessor
from motionile.modules.media.music_repository import (
    MusicFilter,
    MusicRow,
    MusicStore,
    NewMusicTrack,
    SqlMusicRepository,
)
from motionile.modules.media.schemas import MusicTrackView

type MusicStoreFactory = Callable[[AsyncSession], MusicStore]

EDITABLE_FIELDS = frozenset({"title", "mood", "bpm", "license_name", "license_url", "attribution_text"})
AUDIT_TARGET = "music_track"


@dataclass(frozen=True, slots=True)
class MusicUpload:
    content: bytes
    title: str
    mood: str
    license_name: str
    license_url: str
    bpm: int | None = None
    attribution_text: str | None = None
    activate: bool = False


@dataclass(frozen=True, slots=True)
class MusicPage:
    items: list[MusicTrackView]
    next_cursor: Cursor | None


class MusicService:
    def __init__(
        self,
        assets: AssetService,
        storage: Storage,
        processor: MusicAudioProcessor,
        *,
        preview_ttl: timedelta,
        store_factory: MusicStoreFactory = SqlMusicRepository,
    ) -> None:
        self._assets = assets
        self._storage = storage
        self._processor = processor
        self._preview_ttl = preview_ttl
        self._store_factory = store_factory

    async def upload(
        self, session: AsyncSession, actor_id: UUID, upload: MusicUpload, context: AuditContext | None = None
    ) -> MusicTrackView:
        processed = await self._processor.process(upload.content)
        track_id = new_id()
        asset = await self._assets.store_bytes(
            session,
            processed.data,
            AssetSpec(
                key=music_key(track_id, MUSIC_EXTENSION),
                kind=AssetKind.AUDIO,
                content_type=MUSIC_CONTENT_TYPE,
                duration_ms=processed.duration_ms,
            ),
        )
        row = await self._store_factory(session).insert(
            NewMusicTrack(
                id=track_id,
                title=upload.title,
                audio_asset_id=asset.id,
                mood=upload.mood,
                bpm=upload.bpm,
                duration_ms=processed.duration_ms,
                license_name=upload.license_name,
                license_url=upload.license_url,
                attribution_text=upload.attribution_text,
                is_active=upload.activate,
                created_by_user_id=actor_id,
            ),
            asset.storage_key,
        )
        created = {
            "title": upload.title,
            "mood": upload.mood,
            "licenseName": upload.license_name,
            "durationMs": processed.duration_ms,
            "active": upload.activate,
        }
        await record_audit(session, self._event(actor_id, "music.created", track_id, created), context)
        return await self._view(row)

    async def get(self, session: AsyncSession, track_id: UUID) -> MusicTrackView:
        return await self._view(await self._require(session, track_id))

    async def require_active(self, session: AsyncSession, track_id: UUID) -> MusicTrackView:
        row = await self._store_factory(session).get(track_id)
        if row is None or not row.track.is_active:
            raise MusicTrackUnavailableError
        return await self._view(row)

    async def list_tracks(
        self,
        session: AsyncSession,
        music_filter: MusicFilter,
        cursor: Cursor | None,
        limit: int,
    ) -> MusicPage:
        rows = await self._store_factory(session).page(music_filter, cursor, limit)
        shown = rows[:limit]
        next_cursor = Cursor(shown[-1].track.created_at, shown[-1].track.id) if len(rows) > limit and shown else None
        return MusicPage([await self._view(row) for row in shown], next_cursor)

    async def update(
        self,
        session: AsyncSession,
        actor_id: UUID,
        track_id: UUID,
        changes: Mapping[str, Any],
        context: AuditContext | None = None,
    ) -> MusicTrackView:
        values = {name: value for name, value in changes.items() if name in EDITABLE_FIELDS}
        if not values:
            raise MusicUpdateEmptyError
        await self._require(session, track_id)
        row = await self._store_factory(session).update(track_id, values)
        if row is None:
            raise MusicTrackNotFoundError
        await record_audit(
            session, self._event(actor_id, "music.updated", track_id, {"fields": sorted(values)}), context
        )
        return await self._view(row)

    async def activate(
        self, session: AsyncSession, actor_id: UUID, track_id: UUID, context: AuditContext | None = None
    ) -> MusicTrackView:
        return await self._set_active(session, actor_id, track_id, active=True, context=context)

    async def deactivate(
        self, session: AsyncSession, actor_id: UUID, track_id: UUID, context: AuditContext | None = None
    ) -> MusicTrackView:
        return await self._set_active(session, actor_id, track_id, active=False, context=context)

    async def _set_active(
        self, session: AsyncSession, actor_id: UUID, track_id: UUID, *, active: bool, context: AuditContext | None
    ) -> MusicTrackView:
        current = await self._require(session, track_id)
        if current.track.is_active == active:
            return await self._view(current)
        row = await self._store_factory(session).update(track_id, {"is_active": active})
        if row is None:
            raise MusicTrackNotFoundError
        action = "music.activated" if active else "music.deactivated"
        await record_audit(session, self._event(actor_id, action, track_id, {"title": row.track.title}), context)
        return await self._view(row)

    async def _require(self, session: AsyncSession, track_id: UUID) -> MusicRow:
        row = await self._store_factory(session).get(track_id)
        if row is None:
            raise MusicTrackNotFoundError
        return row

    async def _view(self, row: MusicRow) -> MusicTrackView:
        track = row.track
        return MusicTrackView(
            id=track.id,
            title=track.title,
            mood=track.mood,
            bpm=track.bpm,
            duration_ms=track.duration_ms,
            license_name=track.license_name,
            license_url=track.license_url,
            attribution_text=track.attribution_text,
            is_active=track.is_active,
            audio_asset_id=track.audio_asset_id,
            preview_url=await self._storage.presigned_get_url(row.storage_key, expires_in=self._preview_ttl),
            created_by_user_id=track.created_by_user_id,
            created_at=track.created_at,
            updated_at=track.updated_at,
        )

    @staticmethod
    def _event(actor_id: UUID, action: str, track_id: UUID, metadata: dict[str, Any]) -> AuditEvent:
        return AuditEvent(
            action=action,
            actor_type=ActorType.ADMIN,
            actor_user_id=actor_id,
            target_type=AUDIT_TARGET,
            target_id=str(track_id),
            metadata=metadata,
        )
