import json
import os
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from botocore.exceptions import BotoCoreError
from httpx import AsyncClient, HTTPError, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.credit_support import purge_credit_data
from tests.integration.media_support import MediaApi
from tests.integration.test_auth import csrf

from motionile.core.db import Database
from motionile.core.ids import new_id
from motionile.core.storage.s3 import S3Storage
from motionile.engine.audio.providers.fake import FakeTranscriber, FakeTranscriptMode, FakeVoiceService
from motionile.engine.ffmpeg import FfmpegTools, run_ffmpeg
from motionile.modules.credits import CreditRef, CreditsService, GrantCommand
from motionile.modules.media import build_voice_cloner
from motionile.modules.voices.factory import build_clone_runner
from motionile.modules.voices.runner import RETRYABLE_ERRORS

BASE = "/v1/voices"
STATEMENT_VERSION = "2026-10-19"
RUN_ATTEMPTS = 3
READ_ATTEMPTS = 12
CHUNK = 1024 * 1024
SINE = "sine=frequency=330:duration={seconds}"


def locate_tools() -> FfmpegTools:
    ffmpeg = os.environ.get("RENDER_FFMPEG_PATH") or shutil.which("ffmpeg")
    ffprobe = os.environ.get("RENDER_FFPROBE_PATH") or shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg and ffprobe are unavailable; set RENDER_FFMPEG_PATH and RENDER_FFPROBE_PATH")
    return FfmpegTools(ffmpeg=ffmpeg, ffprobe=ffprobe)


async def make_audio(tools: FfmpegTools, directory: Path, name: str, seconds: int, *arguments: str) -> bytes:
    path = directory / name
    await run_ffmpeg(
        tools,
        ["-f", "lavfi", "-i", SINE.format(seconds=seconds), *arguments, "-y", str(path)],
        timeout_seconds=120,
    )
    return path.read_bytes()


async def make_video(tools: FfmpegTools, directory: Path) -> bytes:
    path = directory / "clip.mp4"
    await run_ffmpeg(
        tools,
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=5:size=64x64:rate=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=330:duration=5",
            "-shortest",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-y",
            str(path),
        ],
        timeout_seconds=120,
    )
    return path.read_bytes()


@dataclass
class VoicesApi:
    media: MediaApi
    enqueued: list[tuple[UUID, UUID | None]] = field(default_factory=list[tuple[UUID, UUID | None]])
    transcriber: FakeTranscriber = field(default_factory=FakeTranscriber)

    @property
    def database(self) -> Database:
        return self.media.database

    @property
    def provider(self) -> FakeVoiceService:
        cloner = build_voice_cloner(self.media.resources)
        assert isinstance(cloner, FakeVoiceService)
        return cloner

    async def run_clone(self, voice_id: UUID, *, sentence: str | None, matching: bool = True) -> None:
        reservation_id = dict(self.enqueued)[voice_id]
        if sentence is not None and matching:
            self.transcriber.mode = FakeTranscriptMode.FIXED
            self.transcriber.fixed_text = sentence
        else:
            self.transcriber.mode = FakeTranscriptMode.WRONG
        runner = build_clone_runner(self.media.resources, self.transcriber)
        for attempt in range(RUN_ATTEMPTS):
            try:
                await runner.run(voice_id, reservation_id)
            except RETRYABLE_ERRORS:
                if attempt == RUN_ATTEMPTS - 1:
                    raise
            else:
                return

    async def fund(self, user_id: UUID, amount: int) -> None:
        resources = self.media.resources
        service = CreditsService(resources.clock, resources.settings.billing)
        async with self.database.transaction() as session:
            await service.grant(
                session,
                GrantCommand(
                    user_id=user_id,
                    amount=amount,
                    source="purchase",
                    key=f"voices-test:{new_id()}",
                    expires_at=None,
                    ref=CreditRef("payment", new_id()),
                ),
            )

    async def set_setting(self, key: str, value: object) -> None:
        resources = self.media.resources
        async with self.database.transaction() as session:
            await session.execute(
                text(
                    "INSERT INTO system_settings (key, value, version) VALUES (:key, CAST(:value AS jsonb), 1) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
                ),
                {"key": key, "value": json.dumps(value)},
            )
        await resources.redis_store.delete(resources.redis_store.keys.key("platform.setting", key))

    async def scalar(self, statement: str, **parameters: Any) -> Any:
        async with self.database.transaction() as session:
            return (await session.execute(text(statement), parameters)).scalar()

    async def rows(self, statement: str, **parameters: Any) -> list[Any]:
        async with self.database.transaction() as session:
            return list((await session.execute(text(statement), parameters)).all())


async def start_attempt(client: AsyncClient) -> Response:
    return await client.post(
        BASE + "/clones",
        json={"statementVersion": STATEMENT_VERSION, "accepted": True},
        headers=csrf(client),
    )


async def put_consent(client: AsyncClient, attempt_id: str, content: bytes, filename: str = "consent.wav") -> Response:
    return await client.put(
        f"{BASE}/clones/{attempt_id}/consent-recording",
        files={"file": (filename, content, "application/octet-stream")},
        headers=csrf(client),
    )


async def post_sample(client: AsyncClient, attempt_id: str, content: bytes, filename: str = "sample.wav") -> Response:
    return await client.post(
        f"{BASE}/clones/{attempt_id}/samples",
        files={"file": (filename, content, "application/octet-stream")},
        headers=csrf(client),
    )


async def submit_attempt(
    client: AsyncClient, attempt_id: str, *, name: str = "My voice", language: str = "en", key: str | None = None
) -> Response:
    return await client.post(
        f"{BASE}/clones/{attempt_id}/submit",
        json={"name": name, "language": language},
        headers={**csrf(client), "Idempotency-Key": key or f"submit-{new_id()}"},
    )


async def purge_voices_data(database: Database) -> None:
    async with database.transaction() as session:
        await _delete_voice_rows(session)
    await purge_credit_data(database, [])


async def _delete_voice_rows(session: AsyncSession) -> None:
    await session.execute(text("DELETE FROM voice_consents"))
    await session.execute(text("UPDATE user_preferences SET default_voice_id = NULL"))
    await session.execute(text("DELETE FROM voices"))
    await session.execute(text("DELETE FROM system_settings WHERE key LIKE 'voices.%'"))


async def create_clone(
    api: VoicesApi, consent: bytes, sample: bytes, *, client: AsyncClient | None = None, samples: int = 2
) -> tuple[dict[str, object], dict[str, object]]:
    caller = client or api.media.primary
    started = await start_attempt(caller)
    assert started.status_code == 201, started.text
    attempt = started.json()
    attempt_id = str(attempt["attemptId"])
    assert (await put_consent(caller, attempt_id, consent)).status_code == 200
    for _ in range(samples):
        assert (await post_sample(caller, attempt_id, sample)).status_code == 201
    submitted = await submit_attempt(caller, attempt_id)
    assert submitted.status_code == 202, submitted.text
    return attempt, submitted.json()


async def ready_clone(api: VoicesApi, consent: bytes, sample: bytes, client: AsyncClient | None = None) -> UUID:
    attempt, voice = await create_clone(api, consent, sample, client=client)
    voice_id = UUID(str(voice["id"]))
    await api.run_clone(voice_id, sentence=str(attempt["consentSentence"]))
    return voice_id


async def set_default_voice(client: AsyncClient, voice_id: str | None) -> Response:
    current = (await client.get("/v1/users/me/preferences")).json()
    return await client.put(
        "/v1/users/me/preferences", json={**current, "defaultVoiceId": voice_id}, headers=csrf(client)
    )


def retry_flaky_object_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    original = S3Storage.get

    async def retrying_get(self: S3Storage, key: str, *, chunk_size: int = CHUNK) -> AsyncIterator[bytes]:
        for attempt in range(READ_ATTEMPTS):
            try:
                data = b"".join([chunk async for chunk in original(self, key, chunk_size=chunk_size)])
            except (BotoCoreError, OSError):
                if attempt == READ_ATTEMPTS - 1:
                    raise
                continue
            for start in range(0, len(data), chunk_size):
                yield data[start : start + chunk_size]
            return

    monkeypatch.setattr(S3Storage, "get", retrying_get)


async def fetch_url(url: str) -> Response:
    async with AsyncClient() as plain:
        for attempt in range(READ_ATTEMPTS):
            try:
                return await plain.get(url)
            except HTTPError:
                if attempt == READ_ATTEMPTS - 1:
                    raise
    raise AssertionError("unreachable")
