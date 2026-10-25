import pytest
from tests.fakes.prompts import PromptWorld
from tests.fakes.settings import deployed_settings, make_settings
from tests.unit.modules.prompts.support import Harness, build_harness

from motionile.core.config import AppEnv, ProvidersMode, Settings
from motionile.engine.ai.prompts import PromptSourceError
from motionile.modules.prompts import PromptSeeder
from motionile.modules.prompts.gate import REQUIRED_SUITES
from motionile.scripts import seed_prompts
from motionile.scripts.seed_prompts import EXIT_REFUSED, main


class Resources:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    return build_harness(monkeypatch)


def wire(monkeypatch: pytest.MonkeyPatch, world: PromptWorld, settings: Settings) -> Resources:
    resources = Resources()

    def build(settings: Settings, *, application_name: str) -> Resources:
        del settings, application_name
        return resources

    def seeder(built: Resources) -> PromptSeeder:
        del built
        return PromptSeeder(world.transaction, world.store)

    monkeypatch.setattr(seed_prompts, "get_settings", lambda: settings)
    monkeypatch.setattr(seed_prompts, "build_resources", build)
    monkeypatch.setattr(seed_prompts, "build_prompt_seeder", seeder)
    return resources


def test_the_bootstrap_flag_is_refused_in_deployed_environments_before_any_database_work(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("the database must not be touched")

    monkeypatch.setattr(seed_prompts, "get_settings", deployed_settings)
    monkeypatch.setattr(seed_prompts, "build_resources", forbidden)

    assert main(["--bootstrap-fake-providers"]) == EXIT_REFUSED
    assert "fake providers" in capsys.readouterr().err


@pytest.mark.parametrize("env", [AppEnv.LOCAL, AppEnv.CI])
def test_the_bootstrap_flag_is_refused_with_live_providers(
    monkeypatch: pytest.MonkeyPatch, env: AppEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("the database must not be touched")

    monkeypatch.setattr(seed_prompts, "get_settings", lambda: make_settings(env, providers_mode=ProvidersMode.LIVE))
    monkeypatch.setattr(seed_prompts, "build_resources", forbidden)

    assert main(["--bootstrap-fake-providers"]) == EXIT_REFUSED
    assert capsys.readouterr().err


def test_the_plain_command_syncs_drafts_and_never_activates(
    monkeypatch: pytest.MonkeyPatch, harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    resources = wire(monkeypatch, harness.world, deployed_settings())

    assert main([]) == 0

    assert len(harness.world.versions) == len(REQUIRED_SUITES)
    assert all(template.active_version_id is None for template in harness.world.templates.values())
    assert "activated 0" in capsys.readouterr().out
    assert resources.closed


def test_the_flag_activates_the_latest_versions_in_fake_local_environments(
    monkeypatch: pytest.MonkeyPatch, harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    resources = wire(monkeypatch, harness.world, make_settings(AppEnv.CI))

    assert main(["--bootstrap-fake-providers"]) == 0

    assert all(template.active_version_id is not None for template in harness.world.templates.values())
    assert f"activated {len(REQUIRED_SUITES)}" in capsys.readouterr().out
    assert main(["--bootstrap-fake-providers"]) == 0
    assert "activated 0" in capsys.readouterr().out
    assert resources.closed


def test_invalid_prompt_sources_fail_the_command(
    monkeypatch: pytest.MonkeyPatch, harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    wire(monkeypatch, harness.world, make_settings(AppEnv.CI))

    def broken() -> None:
        raise PromptSourceError("planner.storyboard.md: broken")

    monkeypatch.setattr(seed_prompts, "load_prompt_sources", broken)

    assert main([]) == seed_prompts.EXIT_INVALID_SOURCES
    assert "broken" in capsys.readouterr().err
    assert harness.world.versions == {}
