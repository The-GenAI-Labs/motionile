import io
from pathlib import Path
from typing import cast

import pytest
from PIL import Image

from motionile.engine.ffmpeg import FfmpegError, FfmpegTools
from motionile.engine.render.capture import ChunkPlan
from motionile.engine.render.encode import (
    RGB_TO_BT709_FILTER,
    concat_listing,
    join_segments,
    segment_arguments,
    segment_path,
    video_encoder_arguments,
    x264_parameters,
)
from motionile.engine.render.models import Aspect, RenderEngineConfig
from motionile.engine.render.mux import ass_filter, escape_filter_value
from motionile.engine.render.thumbnails import clamp_poster_ms, encode_posters


def option_after(arguments: list[str], flag: str) -> str:
    return arguments[arguments.index(flag) + 1]


def test_segment_arguments_encode_h264_high_with_bt709_tags() -> None:
    config = RenderEngineConfig(fps=30, crf=18, preset="medium", parallel_pages=1)

    arguments = segment_arguments(config, Path("out.mp4.part"))

    assert option_after(arguments, "-c:v") == "png"
    assert option_after(arguments, "-f") == "image2pipe"
    assert option_after(arguments, "-framerate") == "30"
    assert option_after(arguments, "-profile:v") == "high"
    assert option_after(arguments, "-preset") == "medium"
    assert option_after(arguments, "-crf") == "18"
    assert option_after(arguments, "-pix_fmt") == "yuv420p"
    assert option_after(arguments, "-colorspace") == "bt709"
    assert option_after(arguments, "-color_primaries") == "bt709"
    assert option_after(arguments, "-color_trc") == "bt709"
    assert option_after(arguments, "-color_range") == "tv"
    assert option_after(arguments, "-fps_mode") == "cfr"
    assert option_after(arguments, "-r") == "30"
    assert option_after(arguments, "-vf") == RGB_TO_BT709_FILTER
    assert "-an" in arguments
    assert arguments[-1] == "out.mp4.part"


def test_conversion_filter_uses_the_bt709_limited_range_matrix() -> None:
    assert "out_color_matrix=bt709" in RGB_TO_BT709_FILTER
    assert "out_range=tv" in RGB_TO_BT709_FILTER
    assert RGB_TO_BT709_FILTER.endswith("format=yuv420p")


def test_x264_uses_a_closed_gop_fixed_threads_and_no_scenecut() -> None:
    config = RenderEngineConfig(fps=25, encoder_threads=3, parallel_pages=1)

    parameters = dict(item.split("=") for item in x264_parameters(config).split(":"))

    assert parameters["open-gop"] == "0"
    assert parameters["scenecut"] == "0"
    assert parameters["bframes"] == "0"
    assert parameters["threads"] == "3"
    assert parameters["keyint"] == parameters["min-keyint"] == "50"
    assert parameters["colorprim"] == parameters["transfer"] == parameters["colormatrix"] == "bt709"
    assert parameters["fullrange"] == "off"


def test_encoder_arguments_never_enable_unsafe_options() -> None:
    arguments = video_encoder_arguments(RenderEngineConfig(parallel_pages=1))

    assert "-no-sandbox" not in arguments
    assert option_after(arguments, "-c:v") == "libx264"


def test_segment_paths_are_zero_padded_and_grouped_by_aspect(tmp_path: Path) -> None:
    path = segment_path(tmp_path, Aspect.PORTRAIT, ChunkPlan(index=7, start_frame=0, end_frame=1))

    assert path == tmp_path / "9x16" / "00007.mp4"


def test_concat_listing_quotes_paths(tmp_path: Path) -> None:
    listing = concat_listing([tmp_path / "a.mp4", tmp_path / "it's.mp4"])

    lines = listing.splitlines()
    assert lines[0] == "ffconcat version 1.0"
    assert lines[1].startswith("file '")
    assert lines[1].endswith("a.mp4'")
    assert "'\\''" in lines[2]


async def test_join_without_segments_fails(tmp_path: Path) -> None:
    with pytest.raises(FfmpegError, match="no segments"):
        await join_segments(FfmpegTools(), [], tmp_path / "out.mp4")


def test_filter_values_escape_colons_quotes_and_backslashes() -> None:
    assert escape_filter_value("C:\\fonts\\a'b.ass") == "'C\\:/fonts/a\\'b.ass'"


def test_ass_filter_includes_the_font_directory(tmp_path: Path) -> None:
    value = ass_filter(tmp_path / "subs.ass", tmp_path / "fonts")

    assert value.startswith("ass=filename='")
    assert ":fontsdir='" in value


def test_ass_filter_without_fonts() -> None:
    assert "fontsdir" not in ass_filter(Path("subs.ass"), None)


@pytest.mark.parametrize(
    ("poster_ms", "duration_ms", "expected"),
    [(2000, 10_000, 2000), (2000, 1_000, 967), (0, 500, 0), (5000, 20, 0)],
)
def test_poster_time_is_clamped_to_the_duration(poster_ms: int, duration_ms: int, expected: int) -> None:
    assert clamp_poster_ms(poster_ms, duration_ms, 33) == expected


def test_posters_are_encoded_as_webp_and_jpeg() -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 36), (200, 30, 40)).save(buffer, format="PNG")

    posters = encode_posters(buffer.getvalue())

    with Image.open(io.BytesIO(posters.webp)) as webp, Image.open(io.BytesIO(posters.jpeg)) as jpeg:
        assert webp.format == "WEBP"
        assert jpeg.format == "JPEG"
        assert webp.size == jpeg.size == (64, 36)
        red, green, blue = cast("tuple[int, int, int]", jpeg.convert("RGB").getpixel((10, 10)))
        assert red > 150 > green
        assert blue < 100
