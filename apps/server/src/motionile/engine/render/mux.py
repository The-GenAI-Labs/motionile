from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from motionile.engine.ffmpeg import StreamInfo, probe_file, run_ffmpeg
from motionile.engine.render.encode import video_encoder_arguments
from motionile.engine.render.models import Aspect, OutputCheckError, RenderEngineConfig

MUX_TIMEOUT_SECONDS = 900.0
MAX_AV_DELTA_MS = 100
FRAME_DURATION_TOLERANCE_MS = 2
EXPECTED_SAMPLE_RATE = 48_000
BT709 = "bt709"


def escape_filter_value(value: str) -> str:
    escaped = value.replace("\\", "/").replace("'", "\\'").replace(":", "\\:")
    return f"'{escaped}'"


def ass_filter(ass_path: Path, fonts_directory: Path | None) -> str:
    options = [f"filename={escape_filter_value(ass_path.resolve().as_posix())}"]
    if fonts_directory is not None:
        options.append(f"fontsdir={escape_filter_value(fonts_directory.resolve().as_posix())}")
    return "ass=" + ":".join(options)


@dataclass(frozen=True)
class MuxRequest:
    video: Path
    audio: Path
    output: Path
    ass_path: Path | None = None
    fonts_directory: Path | None = None


async def mux_video(config: RenderEngineConfig, request: MuxRequest) -> Path:
    arguments = ["-y", "-i", str(request.video), "-i", str(request.audio), "-map", "0:v:0", "-map", "1:a:0"]
    if request.ass_path is None:
        arguments.extend(["-c", "copy"])
    else:
        filter_graph = f"{ass_filter(request.ass_path, request.fonts_directory)},format=yuv420p"
        arguments.extend(["-vf", filter_graph, *video_encoder_arguments(config), "-c:a", "copy"])
    arguments.extend(["-movflags", "+faststart", "-f", "mp4", str(request.output)])
    await run_ffmpeg(config.tools, arguments, timeout_seconds=MUX_TIMEOUT_SECONDS)
    return request.output


@dataclass(frozen=True)
class OutputExpectation:
    aspect: Aspect
    frames: int
    fps: int


def check_video_stream(stream: StreamInfo, expectation: OutputExpectation, problems: list[str]) -> None:
    viewport = expectation.aspect.spec.viewport
    if stream.codec_name != "h264":
        problems.append(f"video codec is {stream.codec_name}, expected h264")
    if stream.profile != "High":
        problems.append(f"video profile is {stream.profile}, expected High")
    if stream.pix_fmt != "yuv420p":
        problems.append(f"pixel format is {stream.pix_fmt}, expected yuv420p")
    if (stream.width, stream.height) != (viewport.width, viewport.height):
        problems.append(f"resolution is {stream.width}x{stream.height}, expected {viewport.width}x{viewport.height}")
    tags = {
        "color_space": stream.color_space,
        "color_primaries": stream.color_primaries,
        "color_transfer": stream.color_transfer,
    }
    for name, value in tags.items():
        if value != BT709:
            problems.append(f"{name} is {value}, expected {BT709}")
    if stream.color_range != "tv":
        problems.append(f"color range is {stream.color_range}, expected tv")
    if stream.frame_count != expectation.frames:
        problems.append(f"frame count is {stream.frame_count}, expected {expectation.frames}")
    if stream.frame_rate != Fraction(expectation.fps, 1):
        problems.append(f"frame rate is {stream.frame_rate}, expected {expectation.fps}")


def check_audio_stream(stream: StreamInfo, problems: list[str]) -> None:
    if stream.codec_name != "aac":
        problems.append(f"audio codec is {stream.codec_name}, expected aac")
    if stream.sample_rate != EXPECTED_SAMPLE_RATE:
        problems.append(f"audio sample rate is {stream.sample_rate}, expected {EXPECTED_SAMPLE_RATE}")


async def collect_output_problems(
    config: RenderEngineConfig,
    path: Path,
    expectation: OutputExpectation,
    *,
    expect_audio: bool = True,
) -> list[str]:
    probe = await probe_file(config.tools, path)
    problems: list[str] = []
    videos = probe.video_streams
    audios = probe.audio_streams
    if len(videos) != 1:
        problems.append(f"expected one video stream, found {len(videos)}")
    else:
        check_video_stream(videos[0], expectation, problems)
    if expect_audio:
        if len(audios) != 1:
            problems.append(f"expected one audio stream, found {len(audios)}")
        else:
            check_audio_stream(audios[0], problems)
    if len(videos) == 1 and len(audios) == 1:
        video_ms, audio_ms = videos[0].duration_ms, audios[0].duration_ms
        if video_ms is None or audio_ms is None:
            problems.append("stream durations are unavailable")
        elif abs(video_ms - audio_ms) > MAX_AV_DELTA_MS:
            problems.append(
                f"audio and video differ by {abs(video_ms - audio_ms)} ms; the limit is {MAX_AV_DELTA_MS} ms"
            )
        expected_ms = round(expectation.frames * 1000 / expectation.fps)
        if video_ms is not None and abs(video_ms - expected_ms) > FRAME_DURATION_TOLERANCE_MS * 1000 // expectation.fps:
            problems.append(f"video lasts {video_ms} ms, expected {expected_ms} ms")
    return problems


async def verify_output(
    config: RenderEngineConfig,
    path: Path,
    expectation: OutputExpectation,
    *,
    expect_audio: bool = True,
) -> None:
    problems = await collect_output_problems(config, path, expectation, expect_audio=expect_audio)
    if problems:
        raise OutputCheckError(problems)
