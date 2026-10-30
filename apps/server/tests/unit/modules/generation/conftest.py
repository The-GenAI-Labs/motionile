from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.unit.modules.generation.support import Harness


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    opened = AsyncSession()
    yield opened
    await opened.close()


@pytest.fixture
def harness(session: AsyncSession) -> Harness:
    return Harness(session)
