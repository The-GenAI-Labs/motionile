from collections.abc import AsyncIterator

import pytest_asyncio

from evals.browser import LocalBrowser
from motionile.engine.render.sandbox import RenderSandbox


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def sandbox() -> AsyncIterator[RenderSandbox]:
    async with LocalBrowser().sandbox() as started:
        yield started
