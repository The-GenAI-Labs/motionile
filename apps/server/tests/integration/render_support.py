import asyncio
import json
import shutil
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from botocore.exceptions import BotoCoreError
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.engine.render.support import frame_md5s
from tests.integration.media_support import MediaApi
from tests.integration.test_auth import csrf

from motionile.core.errors import NotFoundError
from motionile.core.storage.base import DEFAULT_CHUNK_SIZE, ObjectInfo, Storage
from motionile.engine.ffmpeg import FfmpegTools
from motionile.modules.media import MediaService, RenderPipeline, ResolvedVoice

BED = "/v1/admin/render/testbed"
FAKE_VOICE_ID = UUID("018f0000-0000-7000-8000-0000000000aa")
UNKNOWN_VOICE_ID = UUID("018f0000-0000-7000-8000-0000000000bb")
SEGMENT_MARKER = "/segments/"
DOWNLOAD_ATTEMPTS = 3


class VoiceNotFoundError(NotFoundError):
    default_code = "voice_not_found"
    title = "Voice not found"


class FakeVoiceLookup:
    async def resolve_selectable(self, session: AsyncSession, user_id: UUID, voice_id: UUID) -> ResolvedVoice:
        del session, user_id
        if voice_id == UNKNOWN_VOICE_ID:
            raise VoiceNotFoundError
        return ResolvedVoice(voice_id=voice_id, provider="fake", provider_voice_id="fake-voice-aria", language="en")


type PutHook = Callable[[str], Awaitable[None]]


class ChaosStorage:
    def __init__(self, inner: Storage) -> None:
        self.inner = inner
        self.before_put: PutHook | None = None
        self.puts: list[str] = []

    async def put(
        self,
        key: str,
        chunks: AsyncIterable[bytes],
        *,
        content_type: str,
        metadata: Mapping[str, str] | None = None,
    ) -> ObjectInfo:
        if self.before_put is not None:
            await self.before_put(key)
        self.puts.append(key)
        return await self.inner.put(key, chunks, content_type=content_type, metadata=metadata)

    def get(self, key: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> AsyncIterator[bytes]:
        return self.inner.get(key, chunk_size=chunk_size)

    async def delete(self, key: str) -> None:
        await self.inner.delete(key)

    async def delete_prefix(self, prefix: str) -> None:
        await self.inner.delete_prefix(prefix)

    async def exists(self, key: str) -> bool:
        return await self.inner.exists(key)

    async def head(self, key: str) -> ObjectInfo | None:
        return await self.inner.head(key)

    async def presigned_get_url(self, key: str, *, expires_in: timedelta, download_filename: str | None = None) -> str:
        return await self.inner.presigned_get_url(key, expires_in=expires_in, download_filename=download_filename)

    async def presigned_put_url(self, key: str, *, content_type: str, expires_in: timedelta) -> str:
        return await self.inner.presigned_put_url(key, content_type=content_type, expires_in=expires_in)


@dataclass
class RenderBed:
    api: MediaApi
    service: MediaService
    pipeline: RenderPipeline
    storage: ChaosStorage
    tools: FfmpegTools
    work: Path
    dispatched: list[UUID] = field(default_factory=list[UUID])

    @property
    def client(self) -> AsyncClient:
        return self.api.primary

    async def post_golden(self, name: str, **options: Any) -> httpx.Response:
        body: dict[str, Any] = {"voiceId": str(FAKE_VOICE_ID), "aspects": ["16:9"], "fps": 24, **options}
        return await self.client.post(f"{BED}/golden/{name}", json=body, headers=csrf(self.client))

    async def post_upload(
        self,
        composition: str,
        options: dict[str, Any],
        parts: Mapping[str, tuple[str, bytes, str]] | None = None,
        client: AsyncClient | None = None,
    ) -> httpx.Response:
        actor = client or self.client
        files: dict[str, tuple[str, bytes, str]] = {
            "composition": ("composition.html", composition.encode(), "text/html"),
            **(parts or {}),
        }
        return await actor.post(BED, data={"options": json.dumps(options)}, files=files, headers=csrf(actor))

    async def run(self, render_id: UUID) -> None:
        await self.pipeline.run(render_id)

    async def state(self, render_id: UUID) -> dict[str, Any]:
        response = await self.client.get(f"{BED}/{render_id}")
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    async def completed(self, render_id: UUID) -> dict[str, Any]:
        body = await self.run_and_read(render_id)
        assert body["status"] == "completed", (body["errorCode"], body["errorMessage"])
        return body

    async def run_and_read(self, render_id: UUID) -> dict[str, Any]:
        await self.run(render_id)
        return await self.state(render_id)

    async def read_object(self, key: str) -> bytes:
        for attempt in range(DOWNLOAD_ATTEMPTS):
            try:
                return b"".join([chunk async for chunk in self.storage.get(key)])
            except (ConnectionError, BotoCoreError):
                if attempt == DOWNLOAD_ATTEMPTS - 1:
                    raise
        raise AssertionError("no download attempts were made")

    async def download(self, key: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(destination.write_bytes, await self.read_object(key))
        return destination

    async def video_hashes(self, user_id: UUID, render_id: UUID, aspect_slug: str, directory: Path) -> list[str]:
        key = f"media/u/{user_id}/renders/{render_id}/{aspect_slug}.mp4"
        path = await self.download(key, directory / f"{render_id}-{aspect_slug}.mp4")
        return await frame_md5s(self.tools, path)

    def leftover_directories(self) -> list[Path]:
        return list(self.work.iterdir()) if self.work.exists() else []

    def clear_work(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)


async def scalar(api: MediaApi, statement: str, **parameters: object) -> Any:
    async with api.database.transaction() as session:
        return (await session.execute(text(statement), parameters)).scalar_one()
