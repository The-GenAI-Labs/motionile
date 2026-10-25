import pytest
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

from motionile.core.config import AppEnv, AppSettings, ProvidersMode
from motionile.modules.prompts.exceptions import BootstrapRefusedError
from motionile.modules.prompts.gate import REQUIRED_SUITES
from motionile.modules.prompts.seed import bootstrap_allowed


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    return build_harness(monkeypatch)


async def test_the_first_sync_creates_a_pending_draft_per_source_and_activates_nothing(harness: Harness) -> None:
    report = await harness.seeder.sync(real_sources())

    assert report.templates_created == len(REQUIRED_SUITES)
    assert len(report.versions_created) == len(REQUIRED_SUITES)
    assert report.unchanged == 0
    for template in harness.world.templates.values():
        assert template.active_version_id is None
        [version] = harness.world.versions_of(template.key)
        assert (version.version, version.eval_status, version.created_by) == (1, "pending", None)
        assert 16 <= len(version.canary) <= 64
        assert "canary" in version.variables
        assert len(version.checksum) == 32
    canaries = {version.canary for version in harness.world.versions.values()}
    assert len(canaries) == len(REQUIRED_SUITES)


async def test_syncing_again_changes_nothing(harness: Harness) -> None:
    await harness.seeder.sync(real_sources())
    versions = {version.id: version.canary for version in harness.world.versions.values()}
    audited = len(harness.audit)

    report = await harness.seeder.sync(real_sources())

    assert (report.templates_created, report.versions_created, report.unchanged) == (0, (), len(REQUIRED_SUITES))
    assert {version.id: version.canary for version in harness.world.versions.values()} == versions
    assert len(harness.audit) == audited


async def test_a_changed_checksum_creates_the_next_draft_and_never_activates_it(harness: Harness) -> None:
    await harness.seed()
    harness.pass_suites()
    await harness.service.activate(ACTOR, KEY, 1)
    first = harness.version(1)

    report = await harness.seeder.sync([source(body=CHANGED_BODY)])

    assert [(item.key, item.version) for item in report.versions_created] == [(KEY, 2)]
    second = harness.version(2)
    assert (second.eval_status, second.created_by) == ("pending", None)
    assert second.canary != first.canary
    assert harness.world.template_by_key(KEY).active_version_id == first.id


async def test_reverting_to_an_older_text_does_not_create_a_duplicate(harness: Harness) -> None:
    await harness.seed()
    await harness.seeder.sync([source(body=CHANGED_BODY)])

    report = await harness.seeder.sync([source(body=BODY)])

    assert report.versions_created == ()
    assert len(harness.world.versions_of(KEY)) == 2


async def test_seeding_is_audited_as_a_system_action(harness: Harness) -> None:
    await harness.seed()

    [event] = harness.audit
    assert (event.action, event.actor_type.value, event.actor_user_id) == ("prompts.draft_created", "system", None)
    assert event.metadata["source"] == "seed"


async def test_bootstrap_activates_the_latest_version_in_fake_local_environments(harness: Harness) -> None:
    await harness.seeder.sync(real_sources())

    activated = await harness.seeder.bootstrap(make_settings(AppEnv.LOCAL).app)

    assert set(activated) == set(REQUIRED_SUITES)
    for template in harness.world.templates.values():
        assert template.active_version_id == harness.world.versions_of(template.key)[-1].id
    again = await harness.seeder.bootstrap(make_settings(AppEnv.CI).app)
    assert again == ()
    assert {event.metadata.get("bootstrap") for event in harness.audit if event.action.endswith("activated")} == {True}


async def test_bootstrap_follows_a_newer_draft_but_keeps_other_templates(harness: Harness) -> None:
    await harness.seed()
    await harness.seeder.bootstrap(make_settings(AppEnv.CI).app)
    await harness.seeder.sync([source(body=CHANGED_BODY)])

    activated = await harness.seeder.bootstrap(make_settings(AppEnv.CI).app)

    assert activated == (KEY,)
    assert harness.world.template_by_key(KEY).active_version_id == harness.version(2).id


@pytest.mark.parametrize(
    ("env", "mode"),
    [
        (AppEnv.STAGING, ProvidersMode.FAKE),
        (AppEnv.PRODUCTION, ProvidersMode.FAKE),
        (AppEnv.LOCAL, ProvidersMode.LIVE),
        (AppEnv.CI, ProvidersMode.LIVE),
    ],
)
async def test_bootstrap_is_refused_outside_fake_local_and_ci(
    harness: Harness, env: AppEnv, mode: ProvidersMode
) -> None:
    await harness.seed()
    app = AppSettings(env=env, providers_mode=mode)

    assert not bootstrap_allowed(app)
    with pytest.raises(BootstrapRefusedError):
        await harness.seeder.bootstrap(app)
    assert harness.world.template_by_key(KEY).active_version_id is None
