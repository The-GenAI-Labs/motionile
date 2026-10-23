import asyncio
import hashlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from motionile.core.config import Settings
from motionile.engine.audio.mix import MixPlan, mix_audio
from motionile.engine.audio.narration import NormalizedAudio, normalize_scene_audio
from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.render.capture import CaptureHooks, CaptureRequest, capture_aspect, plan_chunks, total_frames_for
from motionile.engine.render.encode import ffmpeg_sink_factory, join_segments, segment_path
from motionile.engine.render.models import Aspect, RenderEngineConfig, ValidationReport
from motionile.engine.render.mux import MuxRequest, OutputExpectation, mux_video, verify_output
from motionile.engine.render.runtime import load_runtime_bundle
from motionile.engine.render.sandbox import RenderSandbox
from motionile.engine.render.thumbnails import PosterFiles, PosterTiming, write_posters
from motionile.engine.render.validate import validate_composition
from motionile.modules.media.browser_environment import browser_environment
from motionile.modules.media.pipeline.ports import (
    AssembleJob,
    BrowserValidation,
    CaptureJob,
    PosterJob,
    RenderBrowser,
    SegmentPlan,
)
from motionile.modules.media.providers import ffmpeg_tools

FINGERPRINT_LENGTH = 16


def engine_config(settings: Settings, fps: int) -> RenderEngineConfig:
    render = settings.render
    return RenderEngineConfig(
        fps=fps,
        crf=render.x264_crf,
        preset=render.x264_preset,
        parallel_pages=settings.parallel_render_pages,
        chunk_seconds=render.chunk_seconds,
        tail_ms=render.tail_ms,
        poster_ms=render.poster_ms,
        max_duration_ms=render.max_duration_ms,
        page_load_timeout_seconds=float(render.page_load_timeout_seconds),
        ready_timeout_seconds=float(render.ready_timeout_seconds),
        frame_timeout_seconds=float(render.frame_timeout_seconds),
        browser_memory_mb=render.browser_memory_mb,
        min_free_disk_mb=render.min_free_disk_mb,
        work_directory=render.work_directory,
        browser_environment=browser_environment(settings),
        tools=ffmpeg_tools(settings),
    )


class EngineBrowser:
    def __init__(self, sandbox: RenderSandbox, config: RenderEngineConfig) -> None:
        self._sandbox = sandbox
        self._config = config

    async def validate(self, job: BrowserValidation) -> ValidationReport:
        return await validate_composition(
            self._sandbox, job.html, job.narration, job.aspects, seed=job.seed, should_cancel=job.should_cancel
        )

    async def capture(self, job: CaptureJob) -> None:
        await capture_aspect(
            self._sandbox,
            CaptureRequest(job.html, job.narration, job.aspect, job.seed),
            self._config,
            ffmpeg_sink_factory(self._config, job.segment_directory),
            CaptureHooks(
                completed_chunks=job.completed_chunks,
                on_segment=job.on_segment,
                on_progress=job.on_progress,
                should_cancel=job.should_cancel,
            ),
        )


class EngineToolchain:
    def __init__(self, config: RenderEngineConfig) -> None:
        self._config = config

    @property
    def config(self) -> RenderEngineConfig:
        return self._config

    def plan_segments(self, narration: NarrationDocument, aspect: Aspect, directory: Path) -> SegmentPlan:
        config = self._config
        frames = total_frames_for(narration.total_duration_ms, config.tail_ms, config.fps)
        chunks = plan_chunks(frames, fps=config.fps, chunk_seconds=config.chunk_seconds)
        description = f"{config.fps}:{config.chunk_seconds}:{frames}:{config.crf}:{config.preset}"
        fingerprint = hashlib.sha256(description.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]
        return SegmentPlan(frames, tuple(segment_path(directory, aspect, chunk) for chunk in chunks), fingerprint)

    async def normalize(self, source: bytes, destination: Path) -> NormalizedAudio:
        return await normalize_scene_audio(self._config.tools, source, destination)

    async def mix(self, plan: MixPlan, destination: Path) -> None:
        await mix_audio(self._config.tools, plan, destination)

    @asynccontextmanager
    async def browser(self) -> AsyncGenerator[RenderBrowser]:
        async with RenderSandbox(self._config) as sandbox:
            yield EngineBrowser(sandbox, self._config)

    async def assemble(self, job: AssembleJob) -> Path:
        config = self._config
        await asyncio.to_thread(job.directory.mkdir, parents=True, exist_ok=True)
        label = job.aspect.label
        joined = await join_segments(config.tools, job.segments, job.directory / f"{label}.video.mp4")
        final = await mux_video(
            config,
            MuxRequest(
                video=joined,
                audio=job.audio,
                output=job.directory / f"{label}.mp4",
                ass_path=job.ass_path,
                fonts_directory=job.fonts_directory,
            ),
        )
        await verify_output(config, final, OutputExpectation(job.aspect, job.total_frames, config.fps))
        return final

    async def posters(self, job: PosterJob) -> PosterFiles:
        config = self._config
        timing = PosterTiming(poster_ms=config.poster_ms, duration_ms=job.duration_ms, fps=config.fps)
        return await write_posters(config.tools, job.video, job.directory, job.aspect, timing)

    async def write_fonts(self, directory: Path) -> Path:
        bundle = load_runtime_bundle()
        await asyncio.to_thread(bundle.write_fonts, directory)
        return directory


def build_toolchain(settings: Settings, fps: int) -> EngineToolchain:
    return EngineToolchain(engine_config(settings, fps))
