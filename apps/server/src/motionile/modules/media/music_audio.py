import asyncio
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from motionile.core.errors import AppError
from motionile.engine.audio.audio_validation import AudioRejectedError, AudioUploadLimits, validate_audio_upload
from motionile.engine.audio.mix import transcode_music
from motionile.engine.ffmpeg import FfmpegError, FfmpegTools, probe_file
from motionile.modules.media.exceptions import (
    MusicNotAudioError,
    MusicTooLargeError,
    MusicTooLongError,
    MusicTooShortError,
    MusicTranscodeFailedError,
    MusicUnreadableError,
    MusicUnsupportedFormatError,
    MusicVideoStreamError,
)

MUSIC_MAX_BYTES = 50 * 1024 * 1024
MUSIC_MIN_DURATION_MS = 5_000
MUSIC_MAX_DURATION_MS = 15 * 60 * 1000
MUSIC_LIMITS = AudioUploadLimits(MUSIC_MAX_BYTES, MUSIC_MIN_DURATION_MS, MUSIC_MAX_DURATION_MS)
MUSIC_CONTENT_TYPE = "audio/mp4"
MUSIC_EXTENSION = "m4a"
OUTPUT_NAME = "music.m4a"
TEMP_PREFIX = "motionile-music-"

REJECTIONS: dict[str, type[AppError]] = {
    "not_audio": MusicNotAudioError,
    "too_large": MusicTooLargeError,
    "too_short": MusicTooShortError,
    "too_long": MusicTooLongError,
    "video_stream_present": MusicVideoStreamError,
    "unsupported_format": MusicUnsupportedFormatError,
    "probe_failed": MusicUnreadableError,
}


@dataclass(frozen=True, slots=True)
class ProcessedMusic:
    data: bytes
    duration_ms: int


class MusicAudioProcessor(Protocol):
    async def process(self, data: bytes) -> ProcessedMusic: ...


def rejection_for(error: AudioRejectedError) -> AppError:
    return REJECTIONS.get(error.code, MusicUnreadableError)(error.message)


class FfmpegMusicProcessor:
    def __init__(
        self, tools: FfmpegTools, work_directory: Path | None, limits: AudioUploadLimits = MUSIC_LIMITS
    ) -> None:
        self._tools = tools
        self._work_directory = work_directory
        self._limits = limits

    async def process(self, data: bytes) -> ProcessedMusic:
        try:
            await validate_audio_upload(self._tools, data, self._limits)
        except AudioRejectedError as error:
            raise rejection_for(error) from None
        directory = Path(
            await asyncio.to_thread(
                tempfile.mkdtemp, prefix=TEMP_PREFIX, dir=str(self._work_directory) if self._work_directory else None
            )
        )
        try:
            destination = directory / OUTPUT_NAME
            try:
                await transcode_music(self._tools, data, destination)
                probe = await probe_file(self._tools, destination)
            except FfmpegError:
                raise MusicTranscodeFailedError from None
            duration_ms = probe.duration_ms
            if duration_ms is None or duration_ms <= 0:
                raise MusicTranscodeFailedError
            return ProcessedMusic(await asyncio.to_thread(destination.read_bytes), duration_ms)
        finally:
            await asyncio.to_thread(shutil.rmtree, directory, ignore_errors=True)
