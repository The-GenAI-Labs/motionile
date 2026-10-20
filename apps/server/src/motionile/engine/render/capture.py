import asyncio
import hashlib
import math
import shutil
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.render.models import (
    Aspect,
    CaptureCancelledError,
    DurationLimitError,
    InsufficientDiskError,
    RenderEngineConfig,
    SandboxError,
)
from motionile.engine.render.sandbox import PageSpec

BYTES_PER_MB = 1024 * 1024

type CancelCheck = Callable[[], Awaitable[bool]]
type ProgressCallback = Callable[[int, int], Awaitable[None]]
type SegmentCallback = Callable[[int, Path | None], Awaitable[None]]


class FramePage(Protocol):
    async def capture_frame(self, frame_index: int) -> bytes: ...

    async def close(self) -> None: ...


class PageOpener(Protocol):
    async def open_page(self, spec: PageSpec) -> FramePage: ...


class FrameSink(Protocol):
    async def write(self, frame: bytes) -> None: ...

    async def finish(self) -> Path | None: ...

    async def abort(self) -> None: ...


type SinkFactory = Callable[[Aspect, "ChunkPlan"], Awaitable[FrameSink]]


@dataclass(frozen=True)
class ChunkPlan:
    index: int
    start_frame: int
    end_frame: int

    @property
    def frames(self) -> int:
        return self.end_frame - self.start_frame


@dataclass(frozen=True)
class CaptureResult:
    aspect: Aspect
    total_frames: int
    captured_chunks: tuple[int, ...]
    skipped_chunks: tuple[int, ...]
    peak_parallelism: int
    chunks: tuple[ChunkPlan, ...] = field(default=())


@dataclass
class HashFrameSink:
    hashes: list[str] = field(default_factory=list[str])
    finished: bool = False
    aborted: bool = False

    async def write(self, frame: bytes) -> None:
        self.hashes.append(hashlib.sha256(frame).hexdigest())

    async def finish(self) -> Path | None:
        self.finished = True
        return None

    async def abort(self) -> None:
        self.aborted = True


def total_frames_for(narration_ms: int, tail_ms: int, fps: int) -> int:
    return max(1, math.ceil((narration_ms + tail_ms) * fps / 1000))


def plan_chunks(total_frames: int, *, fps: int, chunk_seconds: int) -> tuple[ChunkPlan, ...]:
    if total_frames < 1 or fps < 1 or chunk_seconds < 1:
        raise ValueError("total_frames, fps and chunk_seconds must be positive")
    size = fps * chunk_seconds
    return tuple(
        ChunkPlan(index=index, start_frame=start, end_frame=min(start + size, total_frames))
        for index, start in enumerate(range(0, total_frames, size))
    )


async def ensure_free_disk(config: RenderEngineConfig) -> None:
    directory = config.resolved_work_directory
    usage = await asyncio.to_thread(shutil.disk_usage, directory)
    if usage.free < config.min_free_disk_mb * BYTES_PER_MB:
        raise InsufficientDiskError(
            f"{usage.free // BYTES_PER_MB} MB free in {directory}; at least {config.min_free_disk_mb} MB are required"
        )


def validate_duration(config: RenderEngineConfig, narration: NarrationDocument) -> None:
    if narration.total_duration_ms > config.max_duration_ms:
        raise DurationLimitError(
            f"The narration lasts {narration.total_duration_ms} ms; the limit is {config.max_duration_ms} ms"
        )


class ChunkQueue:
    def __init__(self, chunks: Iterable[ChunkPlan]) -> None:
        self._queue: asyncio.Queue[ChunkPlan] = asyncio.Queue()
        for chunk in chunks:
            self._queue.put_nowait(chunk)

    def next(self) -> ChunkPlan | None:
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None


@dataclass
class CaptureState:
    total_frames: int
    done_frames: int
    on_progress: ProgressCallback | None
    on_segment: SegmentCallback | None
    should_cancel: CancelCheck | None
    active_pages: int = 0
    peak_pages: int = 0

    async def frame_done(self) -> None:
        self.done_frames += 1
        if self.on_progress is not None:
            await self.on_progress(self.done_frames, self.total_frames)


async def capture_chunk(page: FramePage, chunk: ChunkPlan, sink: FrameSink, state: CaptureState) -> Path | None:
    try:
        for frame in range(chunk.start_frame, chunk.end_frame):
            if state.should_cancel is not None and await state.should_cancel():
                raise CaptureCancelledError("The capture was cancelled")
            await sink.write(await page.capture_frame(frame))
            await state.frame_done()
        return await sink.finish()
    except BaseException:
        await asyncio.shield(sink.abort())
        raise


async def capture_worker(
    opener: PageOpener,
    spec: PageSpec,
    queue: ChunkQueue,
    sink_factory: SinkFactory,
    state: CaptureState,
) -> list[int]:
    captured: list[int] = []
    page: FramePage | None = None
    try:
        while (chunk := queue.next()) is not None:
            if page is None:
                page = await opener.open_page(spec)
                state.active_pages += 1
                state.peak_pages = max(state.peak_pages, state.active_pages)
            sink = await sink_factory(spec.aspect, chunk)
            path = await capture_chunk(page, chunk, sink, state)
            captured.append(chunk.index)
            if state.on_segment is not None:
                await state.on_segment(chunk.index, path)
    finally:
        if page is not None:
            state.active_pages -= 1
            await asyncio.shield(page.close())
    return captured


def first_failure(tasks: Iterable[asyncio.Task[list[int]]]) -> BaseException | None:
    failures = [task.exception() for task in tasks if task.done() and not task.cancelled() and task.exception()]
    ranked = sorted(
        (failure for failure in failures if failure is not None),
        key=lambda failure: (isinstance(failure, CaptureCancelledError), not isinstance(failure, SandboxError)),
    )
    return ranked[0] if ranked else None


async def run_workers(workers: Sequence[Awaitable[list[int]]]) -> list[int]:
    tasks = [asyncio.ensure_future(worker) for worker in workers]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    failure = first_failure(tasks)
    if failure is not None:
        raise failure
    return sorted(index for task in tasks for index in task.result())


@dataclass(frozen=True)
class CaptureRequest:
    html: str
    narration: NarrationDocument
    aspect: Aspect
    seed: int


@dataclass(frozen=True)
class CaptureHooks:
    completed_chunks: Iterable[int] = ()
    on_segment: SegmentCallback | None = None
    on_progress: ProgressCallback | None = None
    should_cancel: CancelCheck | None = None


async def capture_aspect(
    sandbox: PageOpener,
    request: CaptureRequest,
    config: RenderEngineConfig,
    sink_factory: SinkFactory,
    hooks: CaptureHooks | None = None,
) -> CaptureResult:
    hooks = hooks or CaptureHooks()
    narration = request.narration
    validate_duration(config, narration)
    await ensure_free_disk(config)
    total_frames = total_frames_for(narration.total_duration_ms, config.tail_ms, config.fps)
    chunks = plan_chunks(total_frames, fps=config.fps, chunk_seconds=config.chunk_seconds)
    completed = frozenset(hooks.completed_chunks)
    pending = [chunk for chunk in chunks if chunk.index not in completed]
    state = CaptureState(
        total_frames=total_frames,
        done_frames=sum(chunk.frames for chunk in chunks if chunk.index in completed),
        on_progress=hooks.on_progress,
        on_segment=hooks.on_segment,
        should_cancel=hooks.should_cancel,
    )
    captured: list[int] = []
    if pending:
        spec = PageSpec(
            html=request.html, narration=narration, aspect=request.aspect, seed=request.seed, fps=config.fps
        )
        queue = ChunkQueue(pending)
        workers = [
            capture_worker(sandbox, spec, queue, sink_factory, state)
            for _ in range(min(config.parallel_pages, len(pending)))
        ]
        captured = await run_workers(workers)
    return CaptureResult(
        aspect=request.aspect,
        total_frames=total_frames,
        captured_chunks=tuple(captured),
        skipped_chunks=tuple(sorted(completed & {chunk.index for chunk in chunks})),
        peak_parallelism=state.peak_pages,
        chunks=chunks,
    )
