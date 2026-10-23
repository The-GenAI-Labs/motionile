from dataclasses import replace
from pathlib import Path

import pytest
from tests.fakes.render import RecordingSinks
from tests.integration.engine.render.support import TINY_COMPOSITION, frame_md5s, render_config, tiny_narration

from motionile.engine.ffmpeg import FfmpegTools
from motionile.engine.render.capture import (
    CaptureHooks,
    CaptureRequest,
    CaptureResult,
    ChunkPlan,
    HashFrameSink,
    capture_aspect,
)
from motionile.engine.render.models import (
    Aspect,
    CaptureCancelledError,
    RenderEngineConfig,
)
from motionile.engine.render.pipeline import AspectJob, render_aspect
from motionile.engine.render.sandbox import RenderSandbox
from motionile.engine.render.synthetic import synthesize_tone

pytestmark = [pytest.mark.slow, pytest.mark.asyncio(loop_scope="module")]

SEED = 99


def request(aspect: Aspect = Aspect.LANDSCAPE, seed: int = SEED) -> CaptureRequest:
    return CaptureRequest(TINY_COMPOSITION, tiny_narration(), aspect, seed)


async def capture_hashes(
    sandbox: RenderSandbox, config: RenderEngineConfig, *, seed: int = SEED, completed: tuple[int, ...] = ()
) -> tuple[dict[int, str], CaptureResult]:
    sinks = RecordingSinks()
    result = await capture_aspect(sandbox, request(seed=seed), config, sinks, CaptureHooks(completed_chunks=completed))
    return sinks.hashes_by_frame(result.chunks), result


async def test_the_same_inputs_produce_identical_frames(sandbox: RenderSandbox, config: RenderEngineConfig) -> None:
    single = replace(config, parallel_pages=1, fps=20, chunk_seconds=1)

    first, result = await capture_hashes(sandbox, single)
    second, _ = await capture_hashes(sandbox, single)

    assert len(first) == result.total_frames
    assert first == second
    assert len(set(first.values())) > result.total_frames // 4


async def test_parallel_capture_matches_single_page_capture(sandbox: RenderSandbox, config: RenderEngineConfig) -> None:
    base = replace(config, fps=20, chunk_seconds=1)

    single, single_result = await capture_hashes(sandbox, replace(base, parallel_pages=1))
    parallel, parallel_result = await capture_hashes(sandbox, replace(base, parallel_pages=3))

    assert single_result.chunks == parallel_result.chunks
    assert parallel_result.peak_parallelism == 3
    assert single == parallel


async def test_a_different_seed_changes_the_frames(sandbox: RenderSandbox, config: RenderEngineConfig) -> None:
    short = replace(config, parallel_pages=2, fps=10, chunk_seconds=1)

    first, _ = await capture_hashes(sandbox, short, seed=1)
    second, _ = await capture_hashes(sandbox, short, seed=2)

    assert first != second


async def test_resume_recaptures_only_the_missing_chunks(sandbox: RenderSandbox, config: RenderEngineConfig) -> None:
    resumable = replace(config, parallel_pages=2, fps=20, chunk_seconds=1)

    full, full_result = await capture_hashes(sandbox, resumable)
    resumed, resumed_result = await capture_hashes(sandbox, resumable, completed=(0, 2))

    assert resumed_result.skipped_chunks == (0, 2)
    assert set(resumed_result.captured_chunks) == {chunk.index for chunk in full_result.chunks} - {0, 2}
    assert resumed
    assert all(full[frame] == digest for frame, digest in resumed.items())


async def test_cancellation_stops_between_frames(sandbox: RenderSandbox, config: RenderEngineConfig) -> None:
    single = replace(config, parallel_pages=1, fps=20, chunk_seconds=1)
    sink = HashFrameSink()
    seen = 0

    async def should_cancel() -> bool:
        nonlocal seen
        seen += 1
        return seen > 7

    async def only_sink(_aspect: Aspect, _chunk: ChunkPlan) -> HashFrameSink:
        return sink

    with pytest.raises(CaptureCancelledError):
        await capture_aspect(
            sandbox,
            request(),
            single,
            only_sink,
            CaptureHooks(should_cancel=should_cancel),
        )

    assert len(sink.hashes) == 7
    assert sink.aborted is True


async def test_full_renders_are_frame_identical_and_resume_matches(
    sandbox: RenderSandbox, tools: FfmpegTools, tmp_path: Path
) -> None:
    narration = tiny_narration()
    config = render_config(tools, tmp_path, fps=24, chunk_seconds=1)
    audio = await synthesize_tone(tools, tmp_path / "audio.m4a", narration.total_duration_ms + config.tail_ms)

    first = await render_aspect(sandbox, AspectJob(request(), audio, tmp_path / "first"), config)
    second = await render_aspect(sandbox, AspectJob(request(), audio, tmp_path / "second"), config)
    first_hashes = await frame_md5s(tools, first.video)
    second_hashes = await frame_md5s(tools, second.video)

    assert len(first_hashes) == first.capture.total_frames
    assert first_hashes == second_hashes
    assert len(first.capture.chunks) > 3

    missing = first.segments[2]
    missing.unlink()
    resumed = await render_aspect(sandbox, AspectJob(request(), audio, tmp_path / "first"), config)

    assert resumed.capture.captured_chunks == (2,)
    assert resumed.capture.skipped_chunks == tuple(i for i in range(len(first.segments)) if i != 2)
    assert await frame_md5s(tools, resumed.video) == first_hashes
