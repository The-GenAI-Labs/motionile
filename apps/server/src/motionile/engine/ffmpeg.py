import asyncio
import contextlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal, cast

PIPE_PROTOCOLS = "pipe"
FILE_PROTOCOLS = "file,pipe"
PROBE_TIMEOUT_SECONDS = 30.0
STDERR_TAIL_BYTES = 4000

type StreamKind = Literal["audio", "video", "other"]


class FfmpegError(RuntimeError):
    def __init__(self, message: str, *, stderr: str = "", returncode: int | None = None) -> None:
        super().__init__(message)
        self.stderr = stderr
        self.returncode = returncode


class FfmpegTimeoutError(FfmpegError):
    pass


@dataclass(frozen=True)
class FfmpegTools:
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"


@dataclass(frozen=True)
class StreamInfo:
    index: int
    kind: StreamKind
    codec_name: str | None
    profile: str | None
    sample_rate: int | None
    channels: int | None
    width: int | None
    height: int | None
    pix_fmt: str | None
    color_space: str | None
    color_primaries: str | None
    color_transfer: str | None
    color_range: str | None
    frame_count: int | None
    frame_rate: Fraction | None
    duration_ms: int | None
    bit_rate: int | None


@dataclass(frozen=True)
class MediaProbe:
    format_name: str
    duration_ms: int | None
    size_bytes: int | None
    streams: tuple[StreamInfo, ...]

    @property
    def audio_streams(self) -> tuple[StreamInfo, ...]:
        return tuple(stream for stream in self.streams if stream.kind == "audio")

    @property
    def video_streams(self) -> tuple[StreamInfo, ...]:
        return tuple(stream for stream in self.streams if stream.kind == "video")


@dataclass(frozen=True)
class FfmpegResult:
    returncode: int
    stdout: bytes
    stderr: str


def seconds_to_ms(value: object) -> int | None:
    if value is None:
        return None
    try:
        return round(float(cast("float | str", value)) * 1000)
    except (TypeError, ValueError):
        return None


def int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(cast("int | str", value))
    except (TypeError, ValueError):
        return None


def fraction_or_none(value: object) -> Fraction | None:
    if not isinstance(value, str) or "/" not in value:
        return None
    try:
        fraction = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None
    return fraction if fraction > 0 else None


def text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def stream_kind(codec_type: object) -> StreamKind:
    if codec_type == "audio":
        return "audio"
    if codec_type == "video":
        return "video"
    return "other"


def parse_stream(raw: Mapping[str, Any]) -> StreamInfo:
    return StreamInfo(
        index=int_or_none(raw.get("index")) or 0,
        kind=stream_kind(raw.get("codec_type")),
        codec_name=text_or_none(raw.get("codec_name")),
        profile=text_or_none(raw.get("profile")),
        sample_rate=int_or_none(raw.get("sample_rate")),
        channels=int_or_none(raw.get("channels")),
        width=int_or_none(raw.get("width")),
        height=int_or_none(raw.get("height")),
        pix_fmt=text_or_none(raw.get("pix_fmt")),
        color_space=text_or_none(raw.get("color_space")),
        color_primaries=text_or_none(raw.get("color_primaries")),
        color_transfer=text_or_none(raw.get("color_transfer")),
        color_range=text_or_none(raw.get("color_range")),
        frame_count=int_or_none(raw.get("nb_read_frames")) or int_or_none(raw.get("nb_frames")),
        frame_rate=fraction_or_none(raw.get("avg_frame_rate")) or fraction_or_none(raw.get("r_frame_rate")),
        duration_ms=seconds_to_ms(raw.get("duration")),
        bit_rate=int_or_none(raw.get("bit_rate")),
    )


def parse_probe(document: Mapping[str, Any]) -> MediaProbe:
    raw_format = cast("Mapping[str, Any]", document.get("format") or {})
    raw_streams = cast("Sequence[Mapping[str, Any]]", document.get("streams") or [])
    return MediaProbe(
        format_name=str(raw_format.get("format_name") or ""),
        duration_ms=seconds_to_ms(raw_format.get("duration")),
        size_bytes=int_or_none(raw_format.get("size")),
        streams=tuple(parse_stream(stream) for stream in raw_streams),
    )


async def run_process(
    arguments: Sequence[str],
    *,
    timeout_seconds: float,
    stdin: bytes | None = None,
) -> FfmpegResult:
    process = await asyncio.create_subprocess_exec(
        *arguments,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(stdin), timeout=timeout_seconds)
    except TimeoutError as error:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()
        message = f"{Path(arguments[0]).name} did not finish within {timeout_seconds:.0f} seconds"
        raise FfmpegTimeoutError(message) from error
    except BaseException:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()
        raise
    tail = stderr[-STDERR_TAIL_BYTES:].decode("utf-8", errors="replace")
    return FfmpegResult(returncode=process.returncode or 0, stdout=stdout, stderr=tail)


async def run_ffmpeg(
    tools: FfmpegTools,
    arguments: Sequence[str],
    *,
    timeout_seconds: float,
    stdin: bytes | None = None,
) -> FfmpegResult:
    command = [tools.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", *arguments]
    result = await run_process(command, timeout_seconds=timeout_seconds, stdin=stdin)
    if result.returncode != 0:
        message = f"ffmpeg exited with status {result.returncode}"
        raise FfmpegError(message, stderr=result.stderr, returncode=result.returncode)
    return result


def probe_arguments(tools: FfmpegTools, source: str, *, protocols: str, count_frames: bool) -> list[str]:
    arguments = [
        tools.ffprobe,
        "-v",
        "error",
        "-protocol_whitelist",
        protocols,
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
    ]
    if count_frames:
        arguments.append("-count_frames")
    arguments.extend(["-i", source])
    return arguments


async def probe_result(arguments: Sequence[str], *, stdin: bytes | None, timeout_seconds: float) -> MediaProbe:
    result = await run_process(arguments, timeout_seconds=timeout_seconds, stdin=stdin)
    if result.returncode != 0:
        message = f"ffprobe exited with status {result.returncode}"
        raise FfmpegError(message, stderr=result.stderr, returncode=result.returncode)
    try:
        document = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise FfmpegError("ffprobe returned invalid JSON", stderr=result.stderr) from error
    if not isinstance(document, dict):
        raise FfmpegError("ffprobe returned an unexpected document", stderr=result.stderr)
    return parse_probe(cast("Mapping[str, Any]", document))


async def probe_file(
    tools: FfmpegTools,
    path: Path,
    *,
    count_frames: bool = False,
    timeout_seconds: float = PROBE_TIMEOUT_SECONDS,
) -> MediaProbe:
    arguments = probe_arguments(tools, str(path), protocols=FILE_PROTOCOLS, count_frames=count_frames)
    return await probe_result(arguments, stdin=None, timeout_seconds=timeout_seconds)


async def probe_bytes(
    tools: FfmpegTools,
    data: bytes,
    *,
    timeout_seconds: float = PROBE_TIMEOUT_SECONDS,
) -> MediaProbe:
    arguments = probe_arguments(tools, "pipe:0", protocols=PIPE_PROTOCOLS, count_frames=False)
    return await probe_result(arguments, stdin=data, timeout_seconds=timeout_seconds)
