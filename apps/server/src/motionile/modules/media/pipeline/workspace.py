import asyncio
import shutil
import tempfile
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

import structlog

from motionile.core.storage.base import DEFAULT_CHUNK_SIZE, ObjectInfo, Storage
from motionile.modules.media.keys import render_work_key

logger = structlog.get_logger(__name__)


async def file_chunks(path: Path, size: int = DEFAULT_CHUNK_SIZE) -> AsyncIterator[bytes]:
    handle = await asyncio.to_thread(path.open, "rb")
    try:
        while chunk := await asyncio.to_thread(handle.read, size):
            yield chunk
    finally:
        await asyncio.to_thread(handle.close)


async def bytes_chunks(data: bytes) -> AsyncIterator[bytes]:
    yield data


def write_chunk(handle: BinaryIO, chunk: bytes) -> None:
    handle.write(chunk)


class Workspace:
    def __init__(self, storage: Storage, render_id: UUID, root: Path) -> None:
        self._storage = storage
        self._render_id = render_id
        self.root = root

    @classmethod
    @asynccontextmanager
    async def open(cls, storage: Storage, render_id: UUID, parent: Path) -> AsyncGenerator["Workspace"]:
        await asyncio.to_thread(parent.mkdir, parents=True, exist_ok=True)
        root = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix=f"mr-{render_id.hex[:8]}-", dir=parent))
        try:
            yield cls(storage, render_id, root)
        finally:
            await asyncio.to_thread(shutil.rmtree, root, True)

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    def key(self, *parts: str) -> str:
        return render_work_key(self._render_id, *parts)

    async def head(self, key: str) -> ObjectInfo | None:
        return await self._storage.head(key)

    async def exists(self, key: str) -> bool:
        return await self._storage.exists(key)

    async def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        await self._storage.put(key, bytes_chunks(data), content_type=content_type)

    async def put_file(
        self, key: str, path: Path, content_type: str, *, metadata: Mapping[str, str] | None = None
    ) -> None:
        await self._storage.put(key, file_chunks(path), content_type=content_type, metadata=metadata)

    async def get_bytes(self, key: str) -> bytes:
        return b"".join([chunk async for chunk in self._storage.get(key)])

    async def fetch(self, key: str, destination: Path) -> Path:
        if await asyncio.to_thread(destination.is_file):
            return destination
        await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".part")
        handle = await asyncio.to_thread(partial.open, "wb")
        try:
            async for chunk in self._storage.get(key):
                await asyncio.to_thread(write_chunk, handle, chunk)
        except BaseException:
            await asyncio.to_thread(handle.close)
            await asyncio.to_thread(partial.unlink, True)
            raise
        await asyncio.to_thread(handle.close)
        await asyncio.to_thread(partial.replace, destination)
        return destination
