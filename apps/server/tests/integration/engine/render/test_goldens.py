from pathlib import Path

import pytest
from tests.integration.engine.render.support import GOLDEN_NAMES, load_golden, render_config

from motionile.engine.ffmpeg import FfmpegTools, probe_file
from motionile.engine.render.capture import CaptureRequest
from motionile.engine.render.models import Aspect
from motionile.engine.render.pipeline import AspectJob, render_aspect
from motionile.engine.render.sandbox import RenderSandbox
from motionile.engine.render.sanitize import sanitize_composition
from motionile.engine.render.synthetic import synthesize_tone
from motionile.engine.render.thumbnails import PosterTiming, write_posters
from motionile.engine.render.validate import validate_composition

pytestmark = [pytest.mark.slow, pytest.mark.asyncio(loop_scope="module")]

SEED = 20261019
MIN_NARRATION_MS = 10_000
MAX_NARRATION_MS = 25_000
MAX_SYNC_DELTA_MS = 100


@pytest.mark.parametrize("name", GOLDEN_NAMES)
async def test_golden_is_clean_and_valid_in_every_aspect(sandbox: RenderSandbox, name: str) -> None:
    golden = load_golden(name)
    narration = golden.narration()

    sanitized = sanitize_composition(golden.html, scene_ids=golden.scene_ids)
    report = await validate_composition(sandbox, sanitized.html, narration, list(Aspect), seed=SEED)

    assert sanitized.findings == ()
    assert report.errors == ()
    assert report.warnings == ()
    assert 2 <= len(golden.scenes) <= 4 or name == "responsive-scene"
    assert MIN_NARRATION_MS <= narration.total_duration_ms <= MAX_NARRATION_MS
    assert report.stats.aspects == 3
    assert report.stats.samples == 3 * 3 * len(golden.scenes)


@pytest.mark.parametrize("aspect", list(Aspect))
@pytest.mark.parametrize("name", GOLDEN_NAMES)
async def test_golden_renders_to_a_verified_video_in_every_aspect(
    sandbox: RenderSandbox, tools: FfmpegTools, tmp_path: Path, name: str, aspect: Aspect
) -> None:
    golden = load_golden(name)
    narration = golden.narration()
    config = render_config(tools, tmp_path)
    audio = await synthesize_tone(tools, tmp_path / "audio.m4a", narration.total_duration_ms + config.tail_ms)
    sanitized = sanitize_composition(golden.html, scene_ids=golden.scene_ids)

    output = await render_aspect(
        sandbox, AspectJob(CaptureRequest(sanitized.html, narration, aspect, SEED), audio, tmp_path / "work"), config
    )

    probe = await probe_file(tools, output.video, count_frames=True)
    video = probe.video_streams[0]
    sound = probe.audio_streams[0]
    viewport = aspect.spec.viewport
    expected_frames = output.capture.total_frames
    assert (video.width, video.height) == (viewport.width, viewport.height)
    assert video.frame_count == expected_frames
    assert video.codec_name == "h264"
    assert video.profile == "High"
    assert video.pix_fmt == "yuv420p"
    assert (video.color_space, video.color_primaries, video.color_transfer, video.color_range) == (
        "bt709",
        "bt709",
        "bt709",
        "tv",
    )
    assert sound.codec_name == "aac"
    assert sound.sample_rate == 48_000
    assert video.duration_ms is not None
    assert sound.duration_ms is not None
    assert abs(video.duration_ms - sound.duration_ms) <= MAX_SYNC_DELTA_MS
    assert abs(video.duration_ms - (narration.total_duration_ms + config.tail_ms)) <= 1000 // config.fps + 1

    posters = await write_posters(
        tools,
        output.video,
        tmp_path / "posters",
        aspect,
        PosterTiming(poster_ms=config.poster_ms, duration_ms=video.duration_ms, fps=config.fps),
    )
    assert posters.webp.stat().st_size > 1000
    assert posters.jpeg.stat().st_size > 1000
