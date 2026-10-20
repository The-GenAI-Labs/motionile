import asyncio
import contextlib
from collections.abc import Sequence
from pathlib import Path

from motionile.engine.ffmpeg import FfmpegError, FfmpegTools, run_ffmpeg
from motionile.engine.render.capture import ChunkPlan, FrameSink, SinkFactory
from motionile.engine.render.models import Aspect, RenderEngineConfig

SEGMENT_FINISH_TIMEOUT_SECONDS = 300.0
JOIN_TIMEOUT_SECONDS = 600.0
KEYFRAME_INTERVAL_SECONDS = 2
STDERR_TAIL_BYTES = 4000
RGB_TO_BT709_FILTER = (
    "format=rgb24,scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int+bitexact,format=yuv420p"
)
BT709_TAGS = ("-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv")


def x264_parameters(config: RenderEngineConfig) -> str:
    keyframe_interval = config.fps * KEYFRAME_INTERVAL_SECONDS
    return ":".join(
        (
            f"keyint={keyframe_interval}",
            f"min-keyint={keyframe_interval}",
            "scenecut=0",
            "open-gop=0",
            "bframes=0",
            "colorprim=bt709",
            "transfer=bt709",
            "colormatrix=bt709",
            "fullrange=off",
            f"threads={config.encoder_threads}",
        )
    )


def video_encoder_arguments(config: RenderEngineConfig) -> list[str]:
    return [
        "-c:v",
        "libx264",
        "-profile:v",
        "high",
        "-preset",
        config.preset,
        "-crf",
        str(config.crf),
        "-pix_fmt",
        "yuv420p",
        "-x264-params",
        x264_parameters(config),
        *BT709_TAGS,
        "-fps_mode",
        "cfr",
        "-r",
        str(config.fps),
        "-video_track_timescale",
        str(config.fps * 512),
    ]


def segment_arguments(config: RenderEngineConfig, output: Path) -> list[str]:
    return [
        "-y",
        "-f",
        "image2pipe",
        "-framerate",
        str(config.fps),
        "-c:v",
        "png",
        "-i",
        "pipe:0",
        "-vf",
        RGB_TO_BT709_FILTER,
        *video_encoder_arguments(config),
        "-an",
        "-f",
        "mp4",
        str(output),
    ]


class FfmpegSegmentSink:
    def __init__(self, config: RenderEngineConfig, final_path: Path) -> None:
        self._config = config
        self._final_path = final_path
        self._partial_path = final_path.with_name(final_path.name + ".part")
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[bytes] | None = None

    async def start(self) -> None:
        self._final_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self._config.tools.ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            *segment_arguments(self._config, self._partial_path),
        ]
        self._process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        stderr = self._process.stderr
        if stderr is None:
            raise FfmpegError("ffmpeg did not provide a stderr pipe")
        self._stderr_task = asyncio.ensure_future(stderr.read())

    async def _failure(self, message: str) -> FfmpegError:
        process = self._process
        stderr = ""
        if process is not None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
            if self._stderr_task is not None:
                stderr = (await self._stderr_task)[-STDERR_TAIL_BYTES:].decode("utf-8", errors="replace")
        return FfmpegError(message, stderr=stderr, returncode=process.returncode if process else None)

    async def write(self, frame: bytes) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise FfmpegError("The segment encoder is not running")
        try:
            process.stdin.write(frame)
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as error:
            raise await self._failure("ffmpeg stopped reading frames") from error

    async def finish(self) -> Path:
        process = self._process
        if process is None or process.stdin is None:
            raise FfmpegError("The segment encoder is not running")
        process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), SEGMENT_FINISH_TIMEOUT_SECONDS)
        except TimeoutError as error:
            raise await self._failure("ffmpeg did not finish the segment in time") from error
        stderr_task = self._stderr_task
        stderr = (await stderr_task)[-STDERR_TAIL_BYTES:].decode("utf-8", errors="replace") if stderr_task else ""
        if process.returncode != 0:
            raise FfmpegError(
                f"ffmpeg exited with status {process.returncode} while encoding a segment",
                stderr=stderr,
                returncode=process.returncode,
            )
        await asyncio.to_thread(self._partial_path.replace, self._final_path)
        return self._final_path

    async def abort(self) -> None:
        process = self._process
        if process is not None and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
        if self._stderr_task is not None:
            with contextlib.suppress(Exception):
                await self._stderr_task
        await asyncio.to_thread(self._partial_path.unlink, True)


def segment_path(directory: Path, aspect: Aspect, chunk: ChunkPlan) -> Path:
    return directory / aspect.label / f"{chunk.index:05d}.mp4"


def ffmpeg_sink_factory(config: RenderEngineConfig, directory: Path) -> SinkFactory:
    async def create(aspect: Aspect, chunk: ChunkPlan) -> FrameSink:
        sink = FfmpegSegmentSink(config, segment_path(directory, aspect, chunk))
        await sink.start()
        return sink

    return create


def concat_listing(segments: Sequence[Path]) -> str:
    lines = ["ffconcat version 1.0"]
    for segment in segments:
        escaped = segment.resolve().as_posix().replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    return "\n".join(lines) + "\n"


async def join_segments(tools: FfmpegTools, segments: Sequence[Path], output: Path) -> Path:
    if not segments:
        raise FfmpegError("There are no segments to join")
    listing = output.with_name(output.stem + ".concat.txt")
    await asyncio.to_thread(listing.write_text, concat_listing(segments), "utf-8")
    try:
        await run_ffmpeg(
            tools,
            ["-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", "-an", "-f", "mp4", str(output)],
            timeout_seconds=JOIN_TIMEOUT_SECONDS,
        )
    finally:
        await asyncio.to_thread(listing.unlink, True)
    return output
