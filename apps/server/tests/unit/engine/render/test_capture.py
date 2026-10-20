from pathlib import Path

import pytest
from tests.fakes.render import FakePageOpener, RecordingSinks, frame_bytes

from motionile.engine.render.capture import (
    CaptureHooks,
    CaptureRequest,
    HashFrameSink,
    capture_aspect,
    ensure_free_disk,
    plan_chunks,
    total_frames_for,
)
from motionile.engine.render.models import (
    Aspect,
    CaptureCancelledError,
    DurationLimitError,
    InsufficientDiskError,
    PageError,
    RenderEngineConfig,
)
from motionile.engine.render.synthetic import SyntheticScene, build_synthetic_narration

NARRATION = build_synthetic_narration(
    [SyntheticScene("a", "one two three four five six seven"), SyntheticScene("b", "eight nine ten eleven")]
)


def make_config(
    tmp_path: Path,
    *,
    parallel_pages: int = 2,
    chunk_seconds: int = 2,
    max_duration_ms: int = 120_000,
    min_free_disk_mb: int = 1,
) -> RenderEngineConfig:
    return RenderEngineConfig(
        fps=10,
        chunk_seconds=chunk_seconds,
        tail_ms=500,
        parallel_pages=parallel_pages,
        max_duration_ms=max_duration_ms,
        min_free_disk_mb=min_free_disk_mb,
        work_directory=tmp_path,
    )


def make_request() -> CaptureRequest:
    return CaptureRequest(html="<html></html>", narration=NARRATION, aspect=Aspect.LANDSCAPE, seed=3)


def test_total_frames_covers_narration_plus_tail() -> None:
    assert total_frames_for(10_000, 1_000, 30) == 330
    assert total_frames_for(1_001, 0, 30) == 31
    assert total_frames_for(0, 0, 30) == 1


def test_plan_chunks_is_contiguous_and_independent_of_page_count() -> None:
    chunks = plan_chunks(95, fps=10, chunk_seconds=3)

    assert [(chunk.index, chunk.start_frame, chunk.end_frame) for chunk in chunks] == [
        (0, 0, 30),
        (1, 30, 60),
        (2, 60, 90),
        (3, 90, 95),
    ]
    assert sum(chunk.frames for chunk in chunks) == 95


def test_plan_chunks_exact_multiple_has_no_empty_tail() -> None:
    chunks = plan_chunks(60, fps=10, chunk_seconds=3)

    assert [chunk.frames for chunk in chunks] == [30, 30]


def test_plan_chunks_single_short_chunk() -> None:
    assert [chunk.frames for chunk in plan_chunks(1, fps=30, chunk_seconds=5)] == [1]


@pytest.mark.parametrize("arguments", [(0, 30, 5), (10, 0, 5), (10, 30, 0)])
def test_plan_chunks_rejects_non_positive_values(arguments: tuple[int, int, int]) -> None:
    total, fps, seconds = arguments

    with pytest.raises(ValueError, match="positive"):
        plan_chunks(total, fps=fps, chunk_seconds=seconds)


async def test_every_frame_is_captured_once_in_order_within_each_chunk(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    opener = FakePageOpener()
    sinks = RecordingSinks()

    result = await capture_aspect(opener, make_request(), config, sinks)

    total = total_frames_for(NARRATION.total_duration_ms, config.tail_ms, config.fps)
    assert result.total_frames == total
    assert result.captured_chunks == tuple(chunk.index for chunk in result.chunks)
    hashes = sinks.hashes_by_frame(result.chunks)
    assert sorted(hashes) == list(range(total))
    assert all(sink.finished for sink in sinks.sinks.values())
    captured = sorted(frame for page in opener.opened for frame in page.captured)
    assert captured == list(range(total))
    assert all(page.closed for page in opener.opened)


async def test_page_count_never_changes_the_frames(tmp_path: Path) -> None:
    single = RecordingSinks()
    many = RecordingSinks()
    single_config = make_config(tmp_path, parallel_pages=1)
    many_config = make_config(tmp_path, parallel_pages=3)

    single_result = await capture_aspect(FakePageOpener(), make_request(), single_config, single)
    many_result = await capture_aspect(FakePageOpener(), make_request(), many_config, many)

    assert single_result.chunks == many_result.chunks
    assert single.hashes_by_frame(single_result.chunks) == many.hashes_by_frame(many_result.chunks)
    assert single_result.peak_parallelism == 1
    assert many_result.peak_parallelism == 3


async def test_pages_are_limited_to_the_pending_chunks(tmp_path: Path) -> None:
    config = make_config(tmp_path, parallel_pages=8, chunk_seconds=60)
    opener = FakePageOpener()

    result = await capture_aspect(opener, make_request(), config, RecordingSinks())

    assert len(result.chunks) == 1
    assert len(opener.opened) == 1


async def test_completed_chunks_are_skipped_and_counted_as_progress(tmp_path: Path) -> None:
    config = make_config(tmp_path, parallel_pages=1)
    sinks = RecordingSinks()
    progress: list[tuple[int, int]] = []
    segments: list[tuple[int, Path | None]] = []

    async def on_progress(done: int, total: int) -> None:
        progress.append((done, total))

    async def on_segment(index: int, path: Path | None) -> None:
        segments.append((index, path))

    hooks = CaptureHooks(completed_chunks=[0, 2], on_progress=on_progress, on_segment=on_segment)
    result = await capture_aspect(FakePageOpener(), make_request(), config, sinks, hooks)

    assert result.skipped_chunks == (0, 2)
    assert set(sinks.sinks) == {1, *range(3, len(result.chunks))}
    assert [index for index, _ in segments] == sorted(sinks.sinks)
    skipped_frames = sum(chunk.frames for chunk in result.chunks if chunk.index in {0, 2})
    assert progress[0] == (skipped_frames + 1, result.total_frames)
    assert progress[-1] == (result.total_frames, result.total_frames)
    assert [done for done, _ in progress] == sorted(done for done, _ in progress)


async def test_resumed_capture_matches_a_full_capture(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    full = RecordingSinks()
    resumed = RecordingSinks()

    full_result = await capture_aspect(FakePageOpener(), make_request(), config, full)
    await capture_aspect(FakePageOpener(), make_request(), config, resumed, CaptureHooks(completed_chunks=[0, 1]))

    all_hashes = full.hashes_by_frame(full_result.chunks)
    resumed_hashes = resumed.hashes_by_frame(full_result.chunks)
    assert resumed_hashes
    assert min(resumed_hashes) == sum(chunk.frames for chunk in full_result.chunks[:2])
    assert all(all_hashes[frame] == digest for frame, digest in resumed_hashes.items())


async def test_cancellation_stops_between_frames_and_aborts_the_sink(tmp_path: Path) -> None:
    config = make_config(tmp_path, parallel_pages=1)
    sinks = RecordingSinks()
    opener = FakePageOpener()
    checks = 0

    async def should_cancel() -> bool:
        nonlocal checks
        checks += 1
        return checks > 5

    with pytest.raises(CaptureCancelledError):
        await capture_aspect(opener, make_request(), config, sinks, CaptureHooks(should_cancel=should_cancel))

    assert sum(len(page.captured) for page in opener.opened) == 5
    assert sinks.sinks[0].aborted is True
    assert sinks.sinks[0].finished is False
    assert all(page.closed for page in opener.opened)


async def test_a_failing_page_aborts_every_sink_and_closes_every_page(tmp_path: Path) -> None:
    config = make_config(tmp_path, parallel_pages=2)
    sinks = RecordingSinks()
    opener = FakePageOpener(fail_at=3, failure=PageError(["boom"]))

    with pytest.raises(PageError):
        await capture_aspect(opener, make_request(), config, sinks)

    assert all(page.closed for page in opener.opened)
    assert any(sink.aborted for sink in sinks.sinks.values())
    assert not any(sink.finished and sink.hashes == [] for sink in sinks.sinks.values())


async def test_narration_over_the_limit_is_rejected_before_any_page_opens(tmp_path: Path) -> None:
    config = make_config(tmp_path, max_duration_ms=1_000)
    opener = FakePageOpener()

    with pytest.raises(DurationLimitError):
        await capture_aspect(opener, make_request(), config, RecordingSinks())

    assert opener.opened == []


async def test_insufficient_disk_is_rejected(tmp_path: Path) -> None:
    config = make_config(tmp_path, min_free_disk_mb=10**9)

    with pytest.raises(InsufficientDiskError, match="at least"):
        await ensure_free_disk(config)


async def test_hash_sink_records_digests_and_state() -> None:
    sink = HashFrameSink()

    await sink.write(frame_bytes(1))
    await sink.write(frame_bytes(1))
    await sink.write(frame_bytes(2))

    assert sink.hashes[0] == sink.hashes[1] != sink.hashes[2]
    assert await sink.finish() is None
    assert sink.finished is True
    await sink.abort()
    assert sink.aborted is True
