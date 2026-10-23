import hashlib
from collections.abc import AsyncIterable, AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.db import after_commit, after_rollback
from motionile.core.storage.base import DEFAULT_CHUNK_SIZE, Storage, validate_key
from motionile.modules.media.domain import AssetKind, AssetStatus
from motionile.modules.media.exceptions import (
    AssetInUseError,
    AssetKeyExistsError,
    AssetKeyTakenError,
    AssetNotFoundError,
    AssetReferencedError,
    AssetTooLargeError,
)
from motionile.modules.media.models import Asset
from motionile.modules.media.repository import AssetStore, NewAssetRow, SqlAssetRepository

logger = structlog.get_logger(__name__)

type AssetStoreFactory = Callable[[AsyncSession], AssetStore]


@dataclass(frozen=True, slots=True)
class AssetSpec:
    key: str
    kind: AssetKind
    content_type: str
    owner_user_id: UUID | None = None
    duration_ms: int | None = None
    width: int | None = None
    height: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class AssetView:
    id: UUID
    owner_user_id: UUID | None
    kind: AssetKind
    storage_key: str
    content_type: str
    size_bytes: int
    sha256: bytes | None
    duration_ms: int | None
    width: int | None
    height: int | None
    status: AssetStatus
    metadata: Mapping[str, Any]
    created_at: datetime

    @property
    def sha256_hex(self) -> str | None:
        return self.sha256.hex() if self.sha256 is not None else None


def asset_view(asset: Asset) -> AssetView:
    return AssetView(
        id=asset.id,
        owner_user_id=asset.owner_user_id,
        kind=AssetKind(asset.kind),
        storage_key=asset.storage_key,
        content_type=asset.content_type,
        size_bytes=asset.size_bytes,
        sha256=asset.sha256,
        duration_ms=asset.duration_ms,
        width=asset.width,
        height=asset.height,
        status=AssetStatus(asset.status),
        metadata=dict(asset.metadata_),
        created_at=asset.created_at,
    )


class MeasuredChunks:
    def __init__(self, chunks: AsyncIterable[bytes], max_bytes: int | None) -> None:
        self._chunks = chunks
        self._max_bytes = max_bytes
        self._digest = hashlib.sha256()
        self.size_bytes = 0

    @property
    def sha256(self) -> bytes:
        return self._digest.digest()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._chunks:
            self.size_bytes += len(chunk)
            if self._max_bytes is not None and self.size_bytes > self._max_bytes:
                raise AssetTooLargeError
            self._digest.update(chunk)
            yield chunk


async def single_chunk(data: bytes) -> AsyncIterator[bytes]:
    yield data


class AssetService:
    def __init__(self, storage: Storage, store_factory: AssetStoreFactory = SqlAssetRepository) -> None:
        self._storage = storage
        self._store_factory = store_factory

    async def store_bytes(self, session: AsyncSession, data: bytes, spec: AssetSpec) -> AssetView:
        return await self.store_chunks(session, single_chunk(data), spec)

    async def store_chunks(
        self, session: AsyncSession, chunks: AsyncIterable[bytes], spec: AssetSpec, *, max_bytes: int | None = None
    ) -> AssetView:
        validate_key(spec.key)
        store = self._store_factory(session)
        try:
            pending = await store.insert_pending(
                NewAssetRow(
                    owner_user_id=spec.owner_user_id,
                    kind=spec.kind.value,
                    storage_key=spec.key,
                    content_type=spec.content_type,
                    duration_ms=spec.duration_ms,
                    width=spec.width,
                    height=spec.height,
                    metadata=spec.metadata,
                )
            )
        except AssetKeyTakenError as error:
            raise AssetKeyExistsError from error
        measured = MeasuredChunks(chunks, max_bytes)
        try:
            info = await self._storage.put(spec.key, measured, content_type=spec.content_type)
        except BaseException:
            await self._discard(spec.key)
            raise
        after_rollback(session, lambda: self._discard(spec.key))
        ready = await store.mark_ready(pending.id, sha256=measured.sha256, size_bytes=info.size_bytes)
        return asset_view(ready)

    async def get(self, session: AsyncSession, owner_user_id: UUID | None, asset_id: UUID) -> AssetView:
        asset = await self._store_factory(session).get(owner_user_id, asset_id)
        if asset is None:
            raise AssetNotFoundError
        return asset_view(asset)

    async def find_by_key(self, session: AsyncSession, owner_user_id: UUID | None, key: str) -> AssetView | None:
        asset = await self._store_factory(session).get_by_key(owner_user_id, validate_key(key))
        return asset_view(asset) if asset is not None else None

    def read(self, asset: AssetView, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> AsyncIterator[bytes]:
        return self._storage.get(asset.storage_key, chunk_size=chunk_size)

    async def read_bytes(self, asset: AssetView) -> bytes:
        return b"".join([chunk async for chunk in self.read(asset)])

    async def delete(self, session: AsyncSession, owner_user_id: UUID | None, asset_id: UUID) -> None:
        asset = await self.get(session, owner_user_id, asset_id)
        try:
            await self._store_factory(session).delete(owner_user_id, asset_id)
        except AssetReferencedError as error:
            raise AssetInUseError from error
        after_commit(session, lambda: self._discard(asset.storage_key))

    async def delete_by_prefix(self, session: AsyncSession, owner_user_id: UUID | None, prefix: str) -> int:
        validate_key(prefix.rstrip("/"))
        try:
            keys = await self._store_factory(session).delete_by_prefix(owner_user_id, prefix)
        except AssetReferencedError as error:
            raise AssetInUseError from error
        for key in keys:
            after_commit(session, lambda key=key: self._discard(key))
        return len(keys)

    async def _discard(self, key: str) -> None:
        try:
            await self._storage.delete(key)
        except Exception:
            logger.exception("media.asset_object_delete_failed", storage_key=key)
