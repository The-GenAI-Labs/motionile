from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from motionile.core.clock import Clock
from motionile.core.config import VoicesSettings
from motionile.core.errors import AppError
from motionile.engine.audio.audio_validation import (
    AudioRejectedError,
    AudioUploadLimits,
    transcode_to_wav,
    validate_audio_upload,
)
from motionile.engine.audio.providers.elevenlabs import MAX_CLONE_SAMPLES
from motionile.engine.ffmpeg import FfmpegTools
from motionile.modules.voices.exceptions import (
    AudioNotAudioError,
    AudioProbeFailedError,
    AudioTooLargeError,
    AudioTooLongError,
    AudioTooShortError,
    AudioUnsupportedFormatError,
    AudioVideoStreamPresentError,
    CloneAttemptBusyError,
)
from motionile.modules.voices.ports import KeyValueStore

MAX_SAMPLE_FILES = MAX_CLONE_SAMPLES
MIN_SAMPLE_FILE_MS = 1_000
MS_PER_SECOND = 1_000
LOCK_TTL = timedelta(seconds=120)
SUBMISSION_TTL = timedelta(hours=24)
ATTEMPT_NAMESPACE = "voices.attempt"
LOCK_NAMESPACE = "voices.attempt_lock"
SUBMISSION_NAMESPACE = "voices.submission"
WAV_CONTENT_TYPE = "audio/wav"

REJECTIONS: dict[str, type[AppError]] = {
    "not_audio": AudioNotAudioError,
    "too_large": AudioTooLargeError,
    "too_short": AudioTooShortError,
    "too_long": AudioTooLongError,
    "video_stream_present": AudioVideoStreamPresentError,
    "unsupported_format": AudioUnsupportedFormatError,
    "probe_failed": AudioProbeFailedError,
}


class StoredAudio(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset_id: UUID
    duration_ms: int
    size_bytes: int
    index: int = 0


class CloneAttempt(BaseModel):
    model_config = ConfigDict(frozen=True)

    attempt_id: UUID
    user_id: UUID
    voice_id: UUID
    sentence: str
    statement_version: str
    statement_sha256: str
    accepted_at: AwareDatetime
    ip: str | None
    user_agent: str | None
    expires_at: AwareDatetime
    consent: StoredAudio | None = None
    samples: list[StoredAudio] = Field(default_factory=list[StoredAudio])
    next_index: int = 0

    @property
    def total_sample_ms(self) -> int:
        return sum(sample.duration_ms for sample in self.samples)


class CloneSubmission(BaseModel):
    model_config = ConfigDict(frozen=True)

    voice_id: UUID
    user_id: UUID
    sentence: str
    statement_version: str
    statement_sha256: str
    accepted_at: AwareDatetime
    ip: str | None
    user_agent: str | None
    consent_asset_id: UUID
    sample_asset_ids: list[UUID]
    sample_total_ms: int
    credits_reserved: int


@dataclass(frozen=True, slots=True)
class ProcessedAudio:
    data: bytes
    duration_ms: int


class AudioProcessor(Protocol):
    async def process(self, data: bytes, limits: AudioUploadLimits) -> ProcessedAudio: ...


def rejection_for(error: AudioRejectedError) -> AppError:
    return REJECTIONS.get(error.code, AudioProbeFailedError)(error.message)


def sample_limits(settings: VoicesSettings) -> AudioUploadLimits:
    return AudioUploadLimits(
        settings.sample_max_bytes, MIN_SAMPLE_FILE_MS, settings.sample_max_total_seconds * MS_PER_SECOND
    )


def consent_limits(settings: VoicesSettings) -> AudioUploadLimits:
    return AudioUploadLimits(
        settings.sample_max_bytes,
        settings.consent_min_seconds * MS_PER_SECOND,
        settings.consent_max_seconds * MS_PER_SECOND,
    )


class FfmpegAudioProcessor:
    def __init__(self, tools: FfmpegTools) -> None:
        self._tools = tools

    async def process(self, data: bytes, limits: AudioUploadLimits) -> ProcessedAudio:
        try:
            await validate_audio_upload(self._tools, data, limits)
            wav = await transcode_to_wav(self._tools, data, max_duration_ms=limits.max_duration_ms)
        except AudioRejectedError as error:
            raise rejection_for(error) from None
        return ProcessedAudio(wav.data, wav.duration_ms)


class AttemptStore:
    def __init__(self, store: KeyValueStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def _attempt_key(self, attempt_id: UUID) -> str:
        return self._store.keys.key(ATTEMPT_NAMESPACE, attempt_id)

    async def create(self, attempt: CloneAttempt) -> None:
        await self._write(attempt)

    async def save(self, attempt: CloneAttempt) -> bool:
        return await self._write(attempt)

    async def _write(self, attempt: CloneAttempt) -> bool:
        remaining = attempt.expires_at - self._clock.now()
        if remaining <= timedelta(0):
            return False
        await self._store.set(self._attempt_key(attempt.attempt_id), attempt.model_dump_json(), ttl=remaining)
        return True

    async def get(self, attempt_id: UUID, user_id: UUID) -> CloneAttempt | None:
        raw = await self._store.get(self._attempt_key(attempt_id))
        if raw is None:
            return None
        try:
            attempt = CloneAttempt.model_validate_json(raw)
        except ValidationError:
            return None
        if attempt.user_id != user_id or attempt.expires_at <= self._clock.now():
            return None
        return attempt

    async def delete(self, attempt_id: UUID) -> None:
        await self._store.delete(self._attempt_key(attempt_id))

    @asynccontextmanager
    async def locked(self, attempt_id: UUID) -> AsyncGenerator[None]:
        lock_key = self._store.keys.key(LOCK_NAMESPACE, attempt_id)
        if not await self._store.set_if_absent(lock_key, "1", ttl=LOCK_TTL):
            raise CloneAttemptBusyError
        try:
            yield
        finally:
            await self._store.delete(lock_key)

    async def put_submission(self, submission: CloneSubmission) -> None:
        key = self._store.keys.key(SUBMISSION_NAMESPACE, submission.voice_id)
        await self._store.set(key, submission.model_dump_json(), ttl=SUBMISSION_TTL)

    async def get_submission(self, voice_id: UUID) -> CloneSubmission | None:
        raw = await self._store.get(self._store.keys.key(SUBMISSION_NAMESPACE, voice_id))
        if raw is None:
            return None
        try:
            return CloneSubmission.model_validate_json(raw)
        except ValidationError:
            return None

    async def delete_submission(self, voice_id: UUID) -> None:
        await self._store.delete(self._store.keys.key(SUBMISSION_NAMESPACE, voice_id))
