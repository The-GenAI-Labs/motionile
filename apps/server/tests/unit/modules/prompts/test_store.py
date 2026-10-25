import pytest
import structlog
from tests.fakes.prompts import PromptWorld
from tests.fakes.settings import make_settings
from tests.unit.modules.prompts.support import (
    ACTOR,
    BODY,
    CHANGED_BODY,
    KEY,
    Harness,
    build_harness,
    real_sources,
    source,
)

from motionile.core.config import AppEnv
from motionile.engine.ai.prompts import PROMPT_KEYS, render_active
from motionile.modules.prompts import DatabasePromptStore, PromptNotActiveError
from motionile.modules.prompts.exceptions import ActivationBlockedError
from motionile.modules.prompts.store import CACHE_TTL_SECONDS

NEXT = source(body=CHANGED_BODY)


class Ticker:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def store_with(world: PromptWorld, ticker: Ticker) -> DatabasePromptStore:
    return DatabasePromptStore(world.transaction, store_factory=world.store, monotonic=ticker)


@pytest.fixture
async def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    built = build_harness(monkeypatch)
    await built.seed()
    built.pass_suites()
    await built.service.activate(ACTOR, KEY, 1)
    return built


async def test_active_returns_the_version_body_canary_and_variables(harness: Harness) -> None:
    prompt = await harness.store.active(KEY)

    version = harness.version()
    assert (prompt.key, prompt.version, prompt.version_id) == (KEY, 1, version.id)
    assert (prompt.body, prompt.canary, prompt.variables) == (version.body, version.canary, ("canary", "language"))
    assert version.canary in render_active(prompt, {"language": "English"})


async def test_the_prompt_text_and_canary_stay_out_of_reprs_and_logs(harness: Harness) -> None:
    version = harness.version()
    with structlog.testing.capture_logs() as logs:
        prompt = await harness.store.active(KEY)
        await harness.store.all_active()

    assert BODY.strip() not in repr(prompt)
    assert version.canary not in repr(prompt)
    assert version.canary not in str(logs)
    assert BODY.strip() not in str(logs)


async def test_a_template_without_an_active_version_raises_a_typed_error(harness: Harness) -> None:
    await harness.seeder.sync(real_sources())

    with pytest.raises(PromptNotActiveError) as raised:
        await harness.store.active("guard.input")

    assert (raised.value.code, raised.value.status_code, raised.value.key) == ("prompt_not_active", 503, "guard.input")
    with pytest.raises(PromptNotActiveError):
        await harness.store.active("unknown.template")


async def test_results_are_cached_for_thirty_seconds(harness: Harness) -> None:
    ticker = Ticker()
    store = store_with(harness.world, ticker)
    await store.active(KEY)
    opened = harness.world.transactions

    ticker.now += CACHE_TTL_SECONDS - 1
    await store.active(KEY)
    assert harness.world.transactions == opened

    ticker.now += 2
    await store.active(KEY)
    assert harness.world.transactions == opened + 1


async def test_all_active_is_cached_and_fills_the_per_key_cache(harness: Harness) -> None:
    await harness.seeder.sync(real_sources())
    await harness.seeder.bootstrap(make_settings(AppEnv.CI).app)
    ticker = Ticker()
    store = store_with(harness.world, ticker)

    everything = await store.all_active()
    opened = harness.world.transactions
    again = await store.all_active()
    await store.active("guard.input")

    assert {prompt.key for prompt in everything} == set(PROMPT_KEYS)
    assert again == everything
    assert harness.world.transactions == opened


async def test_an_activation_in_the_same_process_invalidates_every_store(harness: Harness) -> None:
    ticker = Ticker()
    first, second = store_with(harness.world, ticker), store_with(harness.world, ticker)
    assert (await first.active(KEY)).version == 1
    assert (await second.all_active())[0].version == 1
    await harness.seeder.sync([NEXT])
    harness.pass_suites(2)

    await harness.service.activate(ACTOR, KEY, 2)

    assert (await first.active(KEY)).version == 2
    assert (await second.all_active())[0].version == 2


async def test_a_rolled_back_activation_leaves_the_cache_untouched(harness: Harness) -> None:
    ticker = Ticker()
    store = store_with(harness.world, ticker)
    await store.active(KEY)
    await harness.seeder.sync([NEXT])

    with pytest.raises(ActivationBlockedError):
        await harness.service.activate(ACTOR, KEY, 2)

    opened = harness.world.transactions
    assert (await store.active(KEY)).version == 1
    assert harness.world.transactions == opened
