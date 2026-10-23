from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.ids import new_id
from motionile.modules.platform.repository import PlatformRepository

SETTING_KEY = "voices.max_cloned_per_user"


async def test_the_first_write_at_the_default_version_creates_the_row(rolled_back_session: AsyncSession) -> None:
    repository = PlatformRepository(rolled_back_session)

    row = await repository.update_setting(SETTING_KEY, 5, 1, None)

    assert row is not None
    assert (row.value, row.version) == (5, 2)
    stored = await repository.setting(SETTING_KEY)
    assert stored is not None
    assert (stored.value, stored.version) == (5, 2)


async def test_a_later_write_needs_the_current_version(rolled_back_session: AsyncSession) -> None:
    repository = PlatformRepository(rolled_back_session)
    await repository.update_setting(SETTING_KEY, 5, 1, None)

    stale = await repository.update_setting(SETTING_KEY, 7, 1, None)
    current = await repository.update_setting(SETTING_KEY, 7, 2, None)

    assert stale is None
    assert current is not None
    assert (current.value, current.version) == (7, 3)


async def test_a_write_with_an_unknown_version_does_not_create_a_row(rolled_back_session: AsyncSession) -> None:
    repository = PlatformRepository(rolled_back_session)

    row = await repository.update_setting(f"voices.unknown_{new_id().hex[:8]}", 5, 4, None)

    assert row is None
