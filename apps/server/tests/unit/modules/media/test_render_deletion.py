from datetime import UTC, datetime, timedelta

import pytest
from tests.fakes.media import World, add_render, add_rendition, fake_session
from tests.fakes.storage import InMemoryStorage, StoredObject
from tests.unit.modules.media.support import USER_A, USER_B

from motionile.core.db import run_after_commit
from motionile.core.ids import new_id
from motionile.modules.media import (
    AssetService,
    MediaService,
    PresignedDelivery,
    RenderNotFinishedError,
    RenderNotFoundError,
    render_media_prefix,
)
from motionile.modules.media.models import Render


def build(world: World, storage: InMemoryStorage) -> MediaService:
    return MediaService(
        PresignedDelivery(storage, timedelta(seconds=900)),
        world.render_store,
        assets=AssetService(storage, world.asset_store),
    )


def stored(storage: InMemoryStorage, key: str) -> None:
    storage.objects[key] = StoredObject(b"data", "video/mp4", {}, datetime.now(UTC))


def seed_render(world: World, storage: InMemoryStorage, **overrides: object) -> tuple[Render, list[str]]:
    render = add_render(world, USER_A, **overrides)
    prefix = render_media_prefix(USER_A, render.id)
    keys = [f"{prefix}16x9.mp4", f"{prefix}poster-16x9.webp", f"{prefix}composition.html"]
    for key in keys:
        world.add_asset(key, owner=USER_A)
        stored(storage, key)
    other = f"{render_media_prefix(USER_A, new_id())}other.mp4"
    world.add_asset(other, owner=USER_A)
    stored(storage, other)
    add_rendition(world, render, "16:9")
    return render, keys


async def test_deleting_a_render_removes_its_rows_assets_and_objects_after_commit() -> None:
    world = World()
    storage = InMemoryStorage()
    render, keys = seed_render(world, storage)
    session = fake_session()

    await build(world, storage).delete_render(session, USER_A, render.id)
    assert all([await storage.exists(key) for key in keys])
    await run_after_commit(session)

    assert world.renders == {}
    assert world.renditions == {}
    assert all([not await storage.exists(key) for key in keys])
    assert len(storage.objects) == 1


@pytest.mark.parametrize("status", ["queued", "capturing", "encoding"])
async def test_a_render_that_has_not_finished_is_kept(status: str) -> None:
    world = World()
    storage = InMemoryStorage()
    render, keys = seed_render(world, storage, status=status, completed_at=None)

    with pytest.raises(RenderNotFinishedError):
        await build(world, storage).delete_render(fake_session(), USER_A, render.id)

    assert render.id in world.renders
    assert all([await storage.exists(key) for key in keys])


async def test_another_users_render_is_not_found_and_untouched() -> None:
    world = World()
    storage = InMemoryStorage()
    render, _ = seed_render(world, storage)

    with pytest.raises(RenderNotFoundError):
        await build(world, storage).delete_render(fake_session(), USER_B, render.id)

    assert render.id in world.renders


async def test_a_service_without_assets_cannot_delete_renders() -> None:
    world = World()
    render = add_render(world, USER_A)
    service = MediaService(PresignedDelivery(InMemoryStorage(), timedelta(seconds=900)), world.render_store)

    with pytest.raises(RuntimeError, match="asset service"):
        await service.delete_render(fake_session(), USER_A, render.id)
