import re
from collections.abc import AsyncIterable, AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

KEY_PATTERN = re.compile(r"^[A-Za-z0-9!_.*'()-]+(/[A-Za-z0-9!_.*'()-]+)*$")
MAX_KEY_LENGTH = 1024
DEFAULT_CHUNK_SIZE = 1024 * 1024


class InvalidStorageKeyError(ValueError):
    def __init__(self, key: str) -> None:
        super().__init__(f"invalid storage key {key!r}")


class ObjectNotFoundError(LookupError):
    def __init__(self, key: str) -> None:
        super().__init__(f"object {key!r} does not exist")
        self.key = key


def validate_key(key: str) -> str:
    if len(key) > MAX_KEY_LENGTH or not KEY_PATTERN.match(key) or ".." in key.split("/"):
        raise InvalidStorageKeyError(key)
    return key


@dataclass(frozen=True)
class ObjectInfo:
    key: str
    size_bytes: int
    content_type: str | None
    etag: str | None
    last_modified: datetime | None
    metadata: Mapping[str, str]


@runtime_checkable
class Storage(Protocol):
    async def put(
        self,
        key: str,
        chunks: AsyncIterable[bytes],
        *,
        content_type: str,
        metadata: Mapping[str, str] | None = None,
    ) -> ObjectInfo: ...

    def get(self, key: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> AsyncIterator[bytes]: ...

    async def delete(self, key: str) -> None: ...

    async def delete_prefix(self, prefix: str) -> None: ...

    async def exists(self, key: str) -> bool: ...

    async def head(self, key: str) -> ObjectInfo | None: ...

    async def presigned_get_url(
        self, key: str, *, expires_in: timedelta, download_filename: str | None = None
    ) -> str: ...

    async def presigned_put_url(self, key: str, *, content_type: str, expires_in: timedelta) -> str: ...
