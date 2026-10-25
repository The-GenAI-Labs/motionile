from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from playwright.async_api import Error as PlaywrightError

from motionile.engine.render.models import RenderEngineConfig
from motionile.engine.render.sandbox import RenderSandbox


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def sandbox(tmp_path_factory: pytest.TempPathFactory) -> AsyncIterator[RenderSandbox]:
    config = RenderEngineConfig(
        fps=15,
        parallel_pages=1,
        page_load_timeout_seconds=30,
        ready_timeout_seconds=30,
        frame_timeout_seconds=20,
        work_directory=tmp_path_factory.mktemp("skill-sandbox"),
    )
    started = RenderSandbox(config)
    try:
        await started.start()
    except PlaywrightError as error:
        pytest.skip(f"Chromium is not available: {error.message.splitlines()[0]}")
    yield started
    await started.close()
