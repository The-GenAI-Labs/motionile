from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from tests.fakes.media import World, add_render, fake_session
from tests.fakes.resources import make_resources
from tests.fakes.settings import make_settings
from tests.fakes.storage import InMemoryStorage
from tests.unit.modules.media.support import NOW, USER_A

from motionile.core.clock import FrozenClock
from motionile.core.ratelimit.policies import DEFAULT_POLICIES, RateLimitScope
from motionile.core.tasks.app import TASK_NAMESPACE, registered_task_app
from motionile.core.tasks.registry import TASK_MODULES
from motionile.modules.media import purge as purge_module
from motionile.modules.media import purge_media
from motionile.modules.media import tasks as tasks_module
from motionile.modules.users import PurgeRegistry, purge_registry

PRUNE_TASK = f"{TASK_NAMESPACE}:media.prune_tts_cache"


async def one_chunk() -> AsyncIterator[bytes]:
    yield b"x"


async def test_the_registry_runs_hooks_in_registration_order() -> None:
    registry = PurgeRegistry()
    calls: list[str] = []

    async def first(resources: object, session: object, user_id: UUID) -> None:
        del resources, session
        calls.append(f"first:{user_id}")

    async def second(resources: object, session: object, user_id: UUID) -> None:
        del resources, session
        calls.append(f"second:{user_id}")

    registry.register("first", first)
    registry.register("second", second)
    await registry.run(make_resources(make_settings()), fake_session(), USER_A)

    assert calls == [f"first:{USER_A}", f"second:{USER_A}"]
    assert registry.names() == ("first", "second")


def test_a_hook_name_can_only_be_registered_once() -> None:
    registry = PurgeRegistry()

    async def hook(resources: object, session: object, user_id: UUID) -> None:
        del resources, session, user_id

    registry.register("media", hook)
    with pytest.raises(ValueError, match="already exists"):
        registry.register("media", hook)


def test_the_media_hook_is_registered_with_the_users_module() -> None:
    assert "media" in purge_registry.names()


async def test_the_media_hook_deletes_the_users_objects_and_nothing_else(monkeypatch: pytest.MonkeyPatch) -> None:
    world = World()
    other = UUID(int=99)
    render = add_render(world, USER_A)
    foreign = add_render(world, other)
    monkeypatch.setattr(purge_module, "SqlRenderRepository", world.render_store)
    resources = make_resources(make_settings())
    storage = InMemoryStorage()
    resources.storage = storage
    keep = [
        f"media/u/{other}/renders/{foreign.id}/16x9.mp4",
        f"work/renders/{foreign.id}/audio.wav",
        f"voice/u/{other}/v1/sample-0.wav",
        f"avatars/{USER_A}/a.webp",
        "tts/ab/abc.mp3",
        "music/track.m4a",
    ]
    remove = [
        f"media/u/{USER_A}/renders/{render.id}/16x9.mp4",
        f"media/u/{USER_A}/renders/{render.id}/poster-16x9.webp",
        f"work/renders/{render.id}/segments/16x9/0.mp4",
        f"voice/u/{USER_A}/v1/sample-0.wav",
        f"voice/u/{USER_A}/v1/consent.wav",
    ]
    for key in [*keep, *remove]:
        await storage.put(key, one_chunk(), content_type="application/octet-stream")

    await purge_media(resources, fake_session(), USER_A)

    assert sorted(storage.objects) == sorted(keep)
    await resources.aclose()


def test_the_prune_task_is_registered_on_the_default_queue_daily() -> None:
    app = registered_task_app()
    registry: dict[tuple[str, str], Any] = vars(app.periodic_registry)["periodic_tasks"]
    schedules = {entry.task.name: entry.cron for entry in registry.values()}
    queues = {name: task.queue for name, task in cast("dict[str, Any]", vars(app)["tasks"]).items()}

    assert "motionile.modules.media.tasks" in TASK_MODULES
    assert schedules[PRUNE_TASK] == "30 3 * * *"
    assert queues[PRUNE_TASK] == "default"


async def test_the_prune_cuts_off_at_ninety_days() -> None:
    cutoffs: list[object] = []

    class Speech:
        async def prune_cache(self, older_than: object) -> int:
            cutoffs.append(older_than)
            return 4

    pruned = await tasks_module.prune_unused_tts_cache(Speech(), FrozenClock(NOW))

    assert pruned == 4
    assert cutoffs == [NOW - timedelta(days=90)]


@pytest.mark.parametrize(
    ("name", "limit", "window"),
    [("media.session", 60, 60), ("music.write", 20, 3600), ("media.upload", 30, 3600)],
)
def test_the_media_rate_limit_policies_exist(name: str, limit: int, window: int) -> None:
    [policy] = [policy for policy in DEFAULT_POLICIES if policy.name == name]
    [rule] = policy.rules

    assert (rule.limit, rule.window_seconds, rule.scope) == (limit, window, RateLimitScope.USER)
