from collections.abc import AsyncIterable, AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from motionile.core.storage.base import DEFAULT_CHUNK_SIZE, ObjectInfo, ObjectNotFoundError, validate_key


@dataclass
class StoredObject:
    data: bytes
    content_type: str
    metadata: dict[str, str]
    last_modified: datetime


@dataclass
class InMemoryStorage:
    objects: dict[str, StoredObject] = field(default_factory=dict[str, StoredObject])

    async def put(
        self,
        key: str,
        chunks: AsyncIterable[bytes],
        *,
        content_type: str,
        metadata: Mapping[str, str] | None = None,
    ) -> ObjectInfo:
        validate_key(key)
        data = b"".join([chunk async for chunk in chunks])
        self.objects[key] = StoredObject(data, content_type, dict(metadata or {}), datetime.now(UTC))
        info = await self.head(key)
        assert info is not None
        return info

    async def get(self, key: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> AsyncIterator[bytes]:
        validate_key(key)
        stored = self.objects.get(key)
        if stored is None:
            raise ObjectNotFoundError(key)
        for start in range(0, len(stored.data), chunk_size):
            yield stored.data[start : start + chunk_size]

    async def delete(self, key: str) -> None:
        validate_key(key)
        self.objects.pop(key, None)

    async def delete_prefix(self, prefix: str) -> None:
        validate_key(prefix.rstrip("/"))
        for key in list(self.objects):
            if key.startswith(prefix):
                del self.objects[key]

    async def exists(self, key: str) -> bool:
        return await self.head(key) is not None

    async def head(self, key: str) -> ObjectInfo | None:
        validate_key(key)
        stored = self.objects.get(key)
        if stored is None:
            return None
        return ObjectInfo(key, len(stored.data), stored.content_type, None, stored.last_modified, stored.metadata)

    async def presigned_get_url(self, key: str, *, expires_in: timedelta, download_filename: str | None = None) -> str:
        validate_key(key)
        suffix = f"&filename={download_filename}" if download_filename else ""
        return f"memory://{key}?expires={int(expires_in.total_seconds())}{suffix}"

    async def presigned_put_url(self, key: str, *, content_type: str, expires_in: timedelta) -> str:
        validate_key(key)
        return f"memory://{key}?put=1&type={content_type}&expires={int(expires_in.total_seconds())}"
