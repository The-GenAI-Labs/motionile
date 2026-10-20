from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text

from motionile.core.db import Database
from motionile.core.ids import new_id
from motionile.core.resources import Resources
from motionile.core.storage.s3 import S3Storage
from motionile.modules.access import grant_role_by_key, invalidate_user_access
from motionile.modules.media import (
    Asset,
    Render,
    Rendition,
    poster_key,
    render_media_prefix,
    rendition_key,
    subtitles_key,
)

DELETE_MEDIA_ROWS = (
    "DELETE FROM renditions",
    "DELETE FROM renders",
    "DELETE FROM tts_cache",
    "DELETE FROM music_tracks",
    "DELETE FROM assets",
)
VIDEO_BYTES = bytes(range(256)) * 16
ROLE_PREFIX = "itest_media_"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


@dataclass
class MediaApi:
    app: FastAPI
    resources: Resources
    storage: S3Storage
    primary: AsyncClient
    other: AsyncClient
    anonymous: AsyncClient
    primary_id: UUID
    other_id: UUID

    @property
    def database(self) -> Database:
        return self.resources.database

    async def grant_role(self, user_id: UUID, role: str) -> None:
        async with self.database.transaction() as session:
            await grant_role_by_key(session, self.resources.redis_store, user_id, role)

    async def grant_permissions(self, user_id: UUID, suffix: str, *permissions: str) -> None:
        key = f"{ROLE_PREFIX}{suffix}"
        async with self.database.transaction() as session:
            role_id = new_id()
            await session.execute(
                text("INSERT INTO roles (id, key, name, is_system) VALUES (:id, :key, :name, false)"),
                {"id": role_id, "key": key, "name": f"Integration {suffix}"},
            )
            await session.execute(
                text(
                    "INSERT INTO role_permissions (role_id, permission_id) "
                    "SELECT :role_id, id FROM permissions WHERE key = ANY(:keys)"
                ),
                {"role_id": role_id, "keys": list(permissions)},
            )
        await self.grant_role(user_id, key)
        await invalidate_user_access(self.resources.redis_store, user_id)

    async def seed_render(
        self, owner: UUID, *, aspects: tuple[str, ...] = ("16:9",), options: dict[str, object] | None = None
    ) -> UUID:
        render_id = new_id()
        prefix = render_media_prefix(owner, render_id)
        async with self.database.transaction() as session:
            composition = self._asset(owner, f"{prefix}composition.html", "html", "text/plain")
            vtt = self._asset(owner, subtitles_key(owner, render_id, "vtt"), "subtitle", "text/vtt")
            srt = self._asset(owner, subtitles_key(owner, render_id, "srt"), "subtitle", "application/x-subrip")
            session.add_all([composition, vtt, srt])
            await session.flush()
            session.add(
                Render(
                    id=render_id,
                    owner_user_id=owner,
                    source="testbed",
                    status="completed",
                    progress=100,
                    options=options or {},
                    composition_asset_id=composition.id,
                    subtitles_vtt_asset_id=vtt.id,
                    subtitles_srt_asset_id=srt.id,
                    duration_ms=5000,
                    started_at=NOW,
                    completed_at=NOW,
                )
            )
            await session.flush()
            for aspect in aspects:
                video = self._asset(owner, rendition_key(owner, render_id, aspect), "video", "video/mp4")
                webp = self._asset(owner, poster_key(owner, render_id, aspect, "webp"), "thumbnail", "image/webp")
                jpeg = self._asset(owner, poster_key(owner, render_id, aspect, "jpg"), "thumbnail", "image/jpeg")
                session.add_all([video, webp, jpeg])
                await session.flush()
                session.add(
                    Rendition(
                        id=new_id(),
                        render_id=render_id,
                        aspect=aspect,
                        width=1920,
                        height=1080,
                        asset_id=video.id,
                        poster_webp_asset_id=webp.id,
                        poster_jpeg_asset_id=jpeg.id,
                        status="ready",
                        duration_ms=5000,
                    )
                )
        for aspect in aspects:
            await self.put_object(rendition_key(owner, render_id, aspect), VIDEO_BYTES, "video/mp4")
        return render_id

    @staticmethod
    def _asset(owner: UUID | None, key: str, kind: str, content_type: str) -> Asset:
        return Asset(
            id=new_id(),
            owner_user_id=owner,
            kind=kind,
            storage_key=key,
            content_type=content_type,
            size_bytes=len(VIDEO_BYTES),
            sha256=bytes(32),
            status="ready",
            metadata_={},
        )

    async def put_object(self, key: str, data: bytes, content_type: str) -> None:
        async def chunks() -> AsyncIterator[bytes]:
            yield data

        await self.storage.put(key, chunks(), content_type=content_type)


async def purge_media_data(database: Database, user_ids: list[UUID]) -> None:
    async with database.transaction() as session:
        await session.execute(text("SET LOCAL motionile.allow_purge = 'on'"))
        await session.execute(text("TRUNCATE usage_records"))
        for statement in DELETE_MEDIA_ROWS:
            await session.execute(text(statement))
        await session.execute(
            text(
                "DELETE FROM audit_log WHERE actor_user_id = ANY(:ids) OR action LIKE 'auth.%' OR action LIKE 'music.%'"
            ),
            {"ids": user_ids},
        )
        await session.execute(text("DELETE FROM user_roles WHERE user_id = ANY(:ids)"), {"ids": user_ids})
        await session.execute(text("DELETE FROM roles WHERE key LIKE 'itest\\_media\\_%'"))
        await session.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": user_ids})
