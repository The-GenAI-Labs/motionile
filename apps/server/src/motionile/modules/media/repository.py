from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.ids import new_id
from motionile.modules.media.domain import AssetKind, AssetStatus
from motionile.modules.media.exceptions import AssetKeyTakenError, AssetReferencedError
from motionile.modules.media.models import Asset, MusicTrack, Render, Rendition

FRESH_ROWS = {"populate_existing": True}
STORAGE_KEY_CONSTRAINT = "uq_assets_storage_key"
FOREIGN_KEY_VIOLATION = "foreign key constraint"


def violates(error: IntegrityError, name: str) -> bool:
    return name in str(error.orig)


@dataclass(frozen=True, slots=True)
class NewAssetRow:
    owner_user_id: UUID | None
    kind: str
    storage_key: str
    content_type: str
    duration_ms: int | None
    width: int | None
    height: int | None
    metadata: Mapping[str, Any]


class AssetStore(Protocol):
    async def insert_pending(self, row: NewAssetRow) -> Asset: ...

    async def mark_ready(self, asset_id: UUID, *, sha256: bytes, size_bytes: int) -> Asset: ...

    async def get(self, owner_user_id: UUID | None, asset_id: UUID) -> Asset | None: ...

    async def get_by_key(self, owner_user_id: UUID | None, storage_key: str) -> Asset | None: ...

    async def delete(self, owner_user_id: UUID | None, asset_id: UUID) -> bool: ...

    async def delete_by_prefix(self, owner_user_id: UUID | None, prefix: str) -> list[str]: ...


class RenderStore(Protocol):
    async def get_render(self, owner_user_id: UUID, render_id: UUID) -> Render | None: ...

    async def renditions(self, render_id: UUID) -> list[Rendition]: ...

    async def assets_by_ids(self, owner_user_id: UUID, asset_ids: Collection[UUID]) -> dict[UUID, Asset]: ...

    async def music_track(self, track_id: UUID) -> MusicTrack | None: ...

    async def render_ids_of(self, owner_user_id: UUID) -> list[UUID]: ...


class SqlAssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def insert_pending(self, row: NewAssetRow) -> Asset:
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
            status=AssetStatus.PENDING.value,
            metadata_=dict(row.metadata),
        )
        try:
            async with self.session.begin_nested():
                self.session.add(asset)
                await self.session.flush()
        except IntegrityError as error:
            if violates(error, STORAGE_KEY_CONSTRAINT):
                raise AssetKeyTakenError from error
            raise
        return asset

    async def mark_ready(self, asset_id: UUID, *, sha256: bytes, size_bytes: int) -> Asset:
        statement = (
            update(Asset)
            .where(Asset.id == asset_id)
            .values(status=AssetStatus.READY.value, sha256=sha256, size_bytes=size_bytes)
            .returning(Asset)
            .execution_options(**FRESH_ROWS)
        )
        return (await self.session.scalars(statement)).one()

    async def get(self, owner_user_id: UUID | None, asset_id: UUID) -> Asset | None:
        statement = (
            select(Asset)
            .where(Asset.id == asset_id, Asset.owner_user_id.is_not_distinct_from(owner_user_id))
            .execution_options(**FRESH_ROWS)
        )
        return await self.session.scalar(statement)

    async def get_by_key(self, owner_user_id: UUID | None, storage_key: str) -> Asset | None:
        statement = (
            select(Asset)
            .where(Asset.storage_key == storage_key, Asset.owner_user_id.is_not_distinct_from(owner_user_id))
            .execution_options(**FRESH_ROWS)
        )
        return await self.session.scalar(statement)

    async def delete(self, owner_user_id: UUID | None, asset_id: UUID) -> bool:
        statement = (
            delete(Asset)
            .where(Asset.id == asset_id, Asset.owner_user_id.is_not_distinct_from(owner_user_id))
            .returning(Asset.id)
        )
        try:
            async with self.session.begin_nested():
                deleted = await self.session.scalar(statement)
        except IntegrityError as error:
            if violates(error, FOREIGN_KEY_VIOLATION):
                raise AssetReferencedError from error
            raise
        return deleted is not None

    async def delete_by_prefix(self, owner_user_id: UUID | None, prefix: str) -> list[str]:
        statement = (
            delete(Asset)
            .where(
                Asset.storage_key.startswith(prefix, autoescape=True),
                Asset.owner_user_id.is_not_distinct_from(owner_user_id),
            )
            .returning(Asset.storage_key)
        )
        try:
            async with self.session.begin_nested():
                return list(await self.session.scalars(statement))
        except IntegrityError as error:
            if violates(error, FOREIGN_KEY_VIOLATION):
                raise AssetReferencedError from error
            raise

    async def voice_sample_owners(self, sha256: bytes) -> list[UUID]:
        statement = select(Asset.owner_user_id).where(
            Asset.kind == AssetKind.VOICE_SAMPLE.value,
            Asset.status == AssetStatus.READY.value,
            Asset.sha256 == sha256,
            Asset.owner_user_id.is_not(None),
        )
        return sorted({owner for owner in await self.session.scalars(statement) if owner is not None})


class SqlRenderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_render(self, owner_user_id: UUID, render_id: UUID) -> Render | None:
        statement = (
            select(Render)
            .where(Render.id == render_id, Render.owner_user_id == owner_user_id)
            .execution_options(**FRESH_ROWS)
        )
        return await self.session.scalar(statement)

    async def renditions(self, render_id: UUID) -> list[Rendition]:
        statement = (
            select(Rendition)
            .where(Rendition.render_id == render_id)
            .order_by(Rendition.created_at, Rendition.id)
            .execution_options(**FRESH_ROWS)
        )
        return list(await self.session.scalars(statement))

    async def assets_by_ids(self, owner_user_id: UUID, asset_ids: Collection[UUID]) -> dict[UUID, Asset]:
        if not asset_ids:
            return {}
        statement = select(Asset).where(Asset.id.in_(asset_ids), Asset.owner_user_id == owner_user_id)
        return {asset.id: asset for asset in await self.session.scalars(statement)}

    async def music_track(self, track_id: UUID) -> MusicTrack | None:
        return await self.session.get(MusicTrack, track_id)

    async def render_ids_of(self, owner_user_id: UUID) -> list[UUID]:
        statement = select(Render.id).where(Render.owner_user_id == owner_user_id).order_by(Render.id)
        return list(await self.session.scalars(statement))
