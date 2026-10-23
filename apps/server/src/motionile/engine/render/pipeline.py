import asyncio
from dataclasses import dataclass
from pathlib import Path

from motionile.engine.render.capture import (
    CaptureHooks,
    CaptureRequest,
    CaptureResult,
    PageOpener,
    capture_aspect,
    plan_chunks,
    total_frames_for,
)
from motionile.engine.render.encode import ffmpeg_sink_factory, join_segments, segment_path
from motionile.engine.render.models import RenderEngineConfig
from motionile.engine.render.mux import MuxRequest, OutputExpectation, mux_video, verify_output


@dataclass(frozen=True)
class AspectOutput:
    video: Path
    segments: tuple[Path, ...]
    capture: CaptureResult


def expected_segments(request: CaptureRequest, config: RenderEngineConfig, directory: Path) -> tuple[Path, ...]:
    frames = total_frames_for(request.narration.total_duration_ms, config.tail_ms, config.fps)
    chunks = plan_chunks(frames, fps=config.fps, chunk_seconds=config.chunk_seconds)
    return tuple(segment_path(directory, request.aspect, chunk) for chunk in chunks)


async def existing_chunk_indexes(segments: tuple[Path, ...]) -> frozenset[int]:
    present = await asyncio.gather(*(asyncio.to_thread(path.is_file) for path in segments))
    return frozenset(index for index, found in enumerate(present) if found)


@dataclass(frozen=True)
class AspectJob:
    request: CaptureRequest
    audio: Path
    work_directory: Path


async def render_aspect(
    sandbox: PageOpener,
    job: AspectJob,
    config: RenderEngineConfig,
    hooks: CaptureHooks | None = None,
) -> AspectOutput:
    hooks = hooks or CaptureHooks()
    request = job.request
    segment_directory = job.work_directory / "segments"
    segments = expected_segments(request, config, segment_directory)
    already = await existing_chunk_indexes(segments)
    merged = CaptureHooks(
        completed_chunks=[*hooks.completed_chunks, *already],
        on_segment=hooks.on_segment,
        on_progress=hooks.on_progress,
        should_cancel=hooks.should_cancel,
    )
    result = await capture_aspect(sandbox, request, config, ffmpeg_sink_factory(config, segment_directory), merged)
    video_directory = job.work_directory / "video"
    await asyncio.to_thread(video_directory.mkdir, parents=True, exist_ok=True)
    joined = await join_segments(config.tools, segments, video_directory / f"{request.aspect.label}.video.mp4")
    final = await mux_video(
        config,
        MuxRequest(video=joined, audio=job.audio, output=video_directory / f"{request.aspect.label}.mp4"),
    )
    await verify_output(config, final, OutputExpectation(request.aspect, result.total_frames, config.fps))
    return AspectOutput(video=final, segments=segments, capture=result)
