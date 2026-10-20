import io
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import pytest
from PIL import Image, ImageChops
from tests.integration.engine.render.support import TINY_COMPOSITION, render_config, tiny_narration

from motionile.engine.ffmpeg import FfmpegTools, probe_file
from motionile.engine.render.capture import CaptureRequest
from motionile.engine.render.models import Aspect, OutputCheckError
from motionile.engine.render.mux import MuxRequest, OutputExpectation, mux_video, verify_output
from motionile.engine.render.pipeline import AspectJob, AspectOutput, render_aspect
from motionile.engine.render.runtime import load_runtime_bundle
from motionile.engine.render.sandbox import RenderSandbox
from motionile.engine.render.synthetic import synthesize_tone
from motionile.engine.render.thumbnails import extract_frame_png

pytestmark = [pytest.mark.slow, pytest.mark.asyncio(loop_scope="module")]

STYLE_FIELDS = (
    "Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
    "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, "
    "MarginV, Encoding"
)
STYLE_VALUES = "Default,Geist,54,&H00FFFFFF,&H000000FF,&H00000000,&H99000000,0,0,0,0,100,100,0,0,3,2,0,2,60,60,60,1"
ASS_DOCUMENT = "\n".join(
    (
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1920",
        "PlayResY: 1080",
        "",
        "[V4+ Styles]",
        f"Format: {STYLE_FIELDS}",
        f"Style: {STYLE_VALUES}",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        "Dialogue: 0,0:00:00.20,0:00:04.00,Default,,0,0,0,,Burned in caption text",
        "",
    )
)


async def rendered(sandbox: RenderSandbox, tools: FfmpegTools, tmp_path: Path) -> tuple[AspectOutput, Path, int]:
    narration = tiny_narration()
    config = render_config(tools, tmp_path, fps=15, chunk_seconds=1)
    audio = await synthesize_tone(tools, tmp_path / "audio.m4a", narration.total_duration_ms + config.tail_ms)
    request = CaptureRequest(TINY_COMPOSITION, narration, Aspect.LANDSCAPE, 5)
    output = await render_aspect(sandbox, AspectJob(request, audio, tmp_path / "work"), config)
    return output, audio, output.capture.total_frames


async def test_subtitles_are_burned_in_with_the_runtime_fonts(
    sandbox: RenderSandbox, tools: FfmpegTools, tmp_path: Path
) -> None:
    output, audio, frames = await rendered(sandbox, tools, tmp_path)
    config = render_config(tools, tmp_path, fps=15, chunk_seconds=1)
    subtitles = tmp_path / "captions.ass"
    subtitles.write_text(ASS_DOCUMENT, encoding="utf-8")
    fonts = tmp_path / "fonts"
    load_runtime_bundle().write_fonts(fonts)
    joined = next((tmp_path / "work" / "video").glob("*.video.mp4"))

    burned = await mux_video(
        config,
        MuxRequest(
            video=joined, audio=audio, output=tmp_path / "burned.mp4", ass_path=subtitles, fonts_directory=fonts
        ),
    )

    await verify_output(config, burned, OutputExpectation(Aspect.LANDSCAPE, frames, config.fps))
    plain = await extract_frame_png(tools, output.video, 1000)
    captioned = await extract_frame_png(tools, burned, 1000)
    with Image.open(io.BytesIO(plain)) as before, Image.open(io.BytesIO(captioned)) as after:
        band = (0, 800, before.width, 1000)
        difference = ImageChops.difference(before.convert("RGB").crop(band), after.convert("RGB").crop(band))
        assert difference.getbbox() is not None
        untouched = (0, 0, before.width, 400)
        top = ImageChops.difference(before.convert("RGB").crop(untouched), after.convert("RGB").crop(untouched))
        extrema = cast("Sequence[tuple[int, int]]", top.getextrema())
        assert max(high for _, high in extrema) < 40


async def test_output_verification_lists_every_problem(
    sandbox: RenderSandbox, tools: FfmpegTools, tmp_path: Path
) -> None:
    output, _, frames = await rendered(sandbox, tools, tmp_path)
    config = render_config(tools, tmp_path, fps=15)

    await verify_output(config, output.video, OutputExpectation(Aspect.LANDSCAPE, frames, 15))
    with pytest.raises(OutputCheckError) as wrong_frames:
        await verify_output(config, output.video, OutputExpectation(Aspect.PORTRAIT, frames + 5, 30))
    video_only = next((tmp_path / "work" / "video").glob("*.video.mp4"))
    with pytest.raises(OutputCheckError) as no_audio:
        await verify_output(config, video_only, OutputExpectation(Aspect.LANDSCAPE, frames, 15))

    problems = "; ".join(wrong_frames.value.problems)
    assert "resolution is 1920x1080, expected 1080x1920" in problems
    assert f"frame count is {frames}, expected {frames + 5}" in problems
    assert "frame rate" in problems
    assert any("audio stream" in problem for problem in no_audio.value.problems)


async def test_joined_segments_keep_every_frame_without_reencoding(
    sandbox: RenderSandbox, tools: FfmpegTools, tmp_path: Path
) -> None:
    output, _, frames = await rendered(sandbox, tools, tmp_path)

    joined = next((tmp_path / "work" / "video").glob("*.video.mp4"))
    probe = await probe_file(tools, joined, count_frames=True)

    assert len(output.segments) > 3
    assert probe.video_streams[0].frame_count == frames
    assert probe.audio_streams == ()
