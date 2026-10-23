from dataclasses import dataclass
from typing import Literal

from motionile.engine.audio.sources import ALLOWED_DEMUXERS, AudioSource, staged_source
from motionile.engine.audio.wav import WavError, finalize_streamed_wav, parse_wav
from motionile.engine.ffmpeg import FfmpegError, FfmpegTools, MediaProbe, StreamInfo, probe_result, run_ffmpeg

type RejectionCode = Literal[
    "not_audio",
    "too_large",
    "too_short",
    "too_long",
    "video_stream_present",
    "unsupported_format",
    "probe_failed",
]

type Container = Literal["wav", "mp3", "aac", "ogg", "flac", "mp4", "matroska"]

CONTAINER_FORMATS: dict[Container, frozenset[str]] = {
    "wav": frozenset({"wav"}),
    "mp3": frozenset({"mp3"}),
    "aac": frozenset({"aac"}),
    "ogg": frozenset({"ogg"}),
    "flac": frozenset({"flac"}),
    "mp4": frozenset({"mov", "mp4"}),
    "matroska": frozenset({"matroska", "webm"}),
}
MAGIC_SIGNATURES: tuple[tuple[Container, bytes, int], ...] = (
    ("ogg", b"OggS", 0),
    ("flac", b"fLaC", 0),
    ("mp4", b"ftyp", 4),
    ("matroska", b"\x1a\x45\xdf\xa3", 0),
    ("mp3", b"ID3", 0),
)
FRAME_HEADER_BYTES = 2
DECODE_SAMPLE_RATE = 8000
BYTES_PER_SAMPLE = 2
MPEG_SYNC_MASK = 0xE0
MPEG_LAYER_MASK = 0x06
ADTS_MASK = 0xF6
ADTS_VALUE = 0xF0
MAGIC_SYNC_BYTE = 0xFF
DECODE_GRACE_SECONDS = 1
VALIDATE_TIMEOUT_SECONDS = 120.0
TRANSCODE_TIMEOUT_SECONDS = 120.0
MS_PER_SECOND = 1000
WAV_SAMPLE_RATE = 44_100
WAV_BYTES_PER_SECOND = WAV_SAMPLE_RATE * 2
WAV_SLACK_BYTES = 4096


class AudioRejectedError(ValueError):
    def __init__(self, code: RejectionCode, message: str) -> None:
        super().__init__(message)
        self.code: RejectionCode = code
        self.message = message


@dataclass(frozen=True, slots=True)
class AudioUploadLimits:
    max_bytes: int
    min_duration_ms: int
    max_duration_ms: int


@dataclass(frozen=True, slots=True)
class ValidatedAudio:
    container: Container
    format_name: str
    codec_name: str | None
    duration_ms: int
    sample_rate: int | None
    channels: int | None
    size_bytes: int


@dataclass(frozen=True, slots=True)
class TranscodedWav:
    data: bytes
    duration_ms: int


def detect_frame_container(head: bytes) -> Container | None:
    if len(head) < FRAME_HEADER_BYTES or head[0] != MAGIC_SYNC_BYTE:
        return None
    if head[1] & ADTS_MASK == ADTS_VALUE:
        return "aac"
    if head[1] & MPEG_SYNC_MASK == MPEG_SYNC_MASK and head[1] & MPEG_LAYER_MASK != 0:
        return "mp3"
    return None


def detect_container(data: bytes) -> Container | None:
    head = data[:12]
    for container, prefix, offset in MAGIC_SIGNATURES:
        if head[offset : offset + len(prefix)] == prefix:
            return container
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    return detect_frame_container(head)


def check_streams(container: Container, probe: MediaProbe) -> StreamInfo:
    if probe.video_streams:
        raise AudioRejectedError("video_stream_present", "the file carries a video stream")
    if not probe.audio_streams:
        raise AudioRejectedError("not_audio", "the file has no audio stream")
    if len(probe.audio_streams) != 1 or len(probe.streams) != 1:
        raise AudioRejectedError("unsupported_format", "the file must hold exactly one audio stream")
    if not CONTAINER_FORMATS[container] & set(probe.format_name.split(",")):
        raise AudioRejectedError("not_audio", "the file content does not match its container")
    return probe.audio_streams[0]


def check_duration(duration_ms: int | None, limits: AudioUploadLimits) -> int:
    if duration_ms is None or duration_ms <= 0:
        raise AudioRejectedError("probe_failed", "the audio duration could not be determined")
    if duration_ms < limits.min_duration_ms:
        raise AudioRejectedError("too_short", "the audio is shorter than the minimum duration")
    if duration_ms > limits.max_duration_ms:
        raise AudioRejectedError("too_long", "the audio is longer than the maximum duration")
    return duration_ms


def validated_from(
    container: Container, probe: MediaProbe, stream: StreamInfo, duration_ms: int, size_bytes: int
) -> ValidatedAudio:
    return ValidatedAudio(
        container=container,
        format_name=probe.format_name,
        codec_name=stream.codec_name,
        duration_ms=duration_ms,
        sample_rate=stream.sample_rate,
        channels=stream.channels,
        size_bytes=size_bytes,
    )


def check_probe(container: Container, probe: MediaProbe, size_bytes: int, limits: AudioUploadLimits) -> ValidatedAudio:
    stream = check_streams(container, probe)
    duration_ms = check_duration(stream.duration_ms or probe.duration_ms, limits)
    return validated_from(container, probe, stream, duration_ms, size_bytes)


def decode_check_arguments(limits: AudioUploadLimits) -> list[str]:
    seconds = limits.max_duration_ms // MS_PER_SECOND + DECODE_GRACE_SECONDS
    return [
        "-xerror",
        "-vn",
        "-map",
        "0:a:0",
        "-t",
        str(seconds),
        "-ac",
        "1",
        "-ar",
        str(DECODE_SAMPLE_RATE),
        "-f",
        "s16le",
        "pipe:1",
    ]


async def decoded_duration_ms(tools: FfmpegTools, source: AudioSource, limits: AudioUploadLimits) -> int:
    try:
        result = await run_ffmpeg(
            tools,
            [*source.arguments, *decode_check_arguments(limits)],
            timeout_seconds=VALIDATE_TIMEOUT_SECONDS,
            stdin=source.stdin,
        )
    except FfmpegError:
        raise AudioRejectedError("probe_failed", "the audio could not be decoded") from None
    return len(result.stdout) * MS_PER_SECOND // (DECODE_SAMPLE_RATE * BYTES_PER_SAMPLE)


async def validate_audio_upload(tools: FfmpegTools, data: bytes, limits: AudioUploadLimits) -> ValidatedAudio:
    if not data:
        raise AudioRejectedError("not_audio", "the file is empty")
    if len(data) > limits.max_bytes:
        raise AudioRejectedError("too_large", "the file exceeds the size limit")
    container = detect_container(data)
    if container is None:
        raise AudioRejectedError("not_audio", "the file is not a recognised audio container")
    async with staged_source(data, formats=ALLOWED_DEMUXERS) as source:
        probe = await probe_with(tools, source.arguments, source.stdin)
        stream = check_streams(container, probe)
        duration_ms = check_duration(await decoded_duration_ms(tools, source, limits), limits)
    return validated_from(container, probe, stream, duration_ms, len(data))


async def probe_with(tools: FfmpegTools, source_arguments: tuple[str, ...], stdin: bytes | None) -> MediaProbe:
    command = [
        tools.ffprobe,
        "-v",
        "error",
        *source_arguments,
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
    ]
    try:
        return await probe_result(command, stdin=stdin, timeout_seconds=VALIDATE_TIMEOUT_SECONDS)
    except FfmpegError:
        raise AudioRejectedError("probe_failed", "the file could not be probed") from None


def wav_arguments(max_duration_ms: int) -> list[str]:
    seconds = max_duration_ms / MS_PER_SECOND
    size_limit = int(seconds * WAV_BYTES_PER_SECOND) + WAV_SLACK_BYTES
    return [
        "-vn",
        "-map",
        "0:a:0",
        "-map_metadata",
        "-1",
        "-t",
        f"{seconds:.3f}",
        "-ac",
        "1",
        "-ar",
        str(WAV_SAMPLE_RATE),
        "-c:a",
        "pcm_s16le",
        "-fs",
        str(size_limit),
        "-f",
        "wav",
        "pipe:1",
    ]


async def transcode_to_wav(
    tools: FfmpegTools,
    data: bytes,
    *,
    max_duration_ms: int,
    timeout_seconds: float = TRANSCODE_TIMEOUT_SECONDS,
) -> TranscodedWav:
    async with staged_source(data, formats=ALLOWED_DEMUXERS) as source:
        try:
            result = await run_ffmpeg(
                tools,
                [*source.arguments, *wav_arguments(max_duration_ms)],
                timeout_seconds=timeout_seconds,
                stdin=source.stdin,
            )
        except FfmpegError:
            raise AudioRejectedError("probe_failed", "the audio could not be converted") from None
    try:
        finalized = finalize_streamed_wav(result.stdout)
        return TranscodedWav(finalized, parse_wav(finalized).duration_ms)
    except WavError:
        raise AudioRejectedError("probe_failed", "the audio could not be converted") from None
