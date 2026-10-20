from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from playwright.async_api import Error as PlaywrightError
from tests.integration.engine.render.support import Canary, leftover_processes, render_config, resolve_tools

from motionile.engine.ffmpeg import FfmpegTools
from motionile.engine.render.models import RenderEngineConfig
from motionile.engine.render.sandbox import RenderSandbox


@pytest.fixture(scope="session")
def tools() -> FfmpegTools:
    found = resolve_tools()
    if found is None:
        pytest.skip("ffmpeg and ffprobe are not available; set RENDER_FFMPEG_PATH and RENDER_FFPROBE_PATH")
    return found


@pytest.fixture
def config(tools: FfmpegTools, tmp_path: Path) -> RenderEngineConfig:
    return render_config(tools, tmp_path)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def sandbox(tools: FfmpegTools, tmp_path_factory: pytest.TempPathFactory) -> AsyncIterator[RenderSandbox]:
    config = render_config(tools, tmp_path_factory.mktemp("sandbox"))
    started = RenderSandbox(config)
    try:
        await started.start()
    except PlaywrightError as error:
        pytest.skip(f"Chromium is not available: {error.message.splitlines()[0]}")
    yield started
    await started.close()
    leftovers = await leftover_processes(started.process_marker)
    assert leftovers == [], f"browser processes outlived the sandbox: {leftovers}"


@pytest_asyncio.fixture(loop_scope="module")
async def canary() -> AsyncIterator[Canary]:
    server = Canary()
    await server.start()
    yield server
    await server.stop()
