import os
import shutil
from pathlib import Path

import pytest
from tests.integration.engine.audio.support import MediaFactory

from motionile.engine.ffmpeg import FfmpegTools


@pytest.fixture(scope="session")
def tools() -> FfmpegTools:
    ffmpeg = os.environ.get("RENDER_FFMPEG_PATH") or shutil.which("ffmpeg")
    ffprobe = os.environ.get("RENDER_FFPROBE_PATH") or shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg and ffprobe are unavailable; set RENDER_FFMPEG_PATH and RENDER_FFPROBE_PATH")
    return FfmpegTools(ffmpeg=ffmpeg, ffprobe=ffprobe)


@pytest.fixture
def media(tools: FfmpegTools, tmp_path: Path) -> MediaFactory:
    directory = tmp_path / "media"
    directory.mkdir()
    return MediaFactory(tools, directory)
