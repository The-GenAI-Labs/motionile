from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.unit.modules.prompts.support import CHANGED_BODY, KEY, Harness, build_harness, real_sources, source

from motionile.core.ids import new_id
from motionile.engine.ai.prompts import PROMPT_KEYS
from motionile.modules.prompts.exceptions import PromptTemplateNotFoundError, PromptVersionNotFoundError
from motionile.modules.prompts.gate import KNOWN_SUITES, REQUIRED_SUITES, required_suites_of


@pytest.fixture
async def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    built = build_harness(monkeypatch)
    await built.seed()
    return built


async def check(harness: Harness, number: int = 1) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    verdict = await harness.gate.check(AsyncSession(), harness.version(number).id)
    return verdict.required, verdict.missing, verdict.failed


def test_every_prompt_key_has_the_required_suites_of_the_adr() -> None:
    assert set(REQUIRED_SUITES) == set(PROMPT_KEYS)
    assert REQUIRED_SUITES == {
        "guard.input": ("safety",),
        "guard.output": ("safety",),
        "router.skills": ("planner", "safety"),
        "planner.storyboard": ("planner", "safety", "cost"),
        "critic.storyboard": ("planner", "safety", "cost"),
        "scene.module": ("scenes", "sync", "safety", "cost"),
        "repair.scene": ("scenes", "sync", "safety", "cost"),
        "review.vision": ("scenes",),
    }
    assert {"planner", "safety", "cost", "scenes", "sync"} == KNOWN_SUITES


def test_an_unmapped_template_has_no_required_suites_to_fall_back_on() -> None:
    with pytest.raises(PromptTemplateNotFoundError):
        required_suites_of("unmapped.template")


async def test_a_version_without_runs_misses_every_required_suite(harness: Harness) -> None:
    required, missing, failed = await check(harness)

    assert required == REQUIRED_SUITES[KEY]
    assert missing == REQUIRED_SUITES[KEY]
    assert failed == ()


async def test_a_version_is_activatable_only_when_every_suite_passed(harness: Harness) -> None:
    version = harness.version()
    for suite in REQUIRED_SUITES[KEY][:-1]:
        harness.world.add_run([version.id], suite)

    verdict = await harness.gate.check(AsyncSession(), version.id)
    assert not verdict.activatable
    assert verdict.missing == (REQUIRED_SUITES[KEY][-1],)

    harness.world.add_run([version.id], REQUIRED_SUITES[KEY][-1])
    verdict = await harness.gate.check(AsyncSession(), version.id)
    assert verdict.activatable
    assert verdict.complete
    assert [result.suite for result in verdict.passed] == list(REQUIRED_SUITES[KEY])


async def test_a_failed_suite_blocks_until_a_later_run_passes(harness: Harness) -> None:
    version = harness.version()
    harness.world.pass_all(KEY, ("planner", "safety"))
    harness.world.add_run([version.id], "cost", passed=False)

    _, missing, failed = await check(harness)
    assert (missing, failed) == ((), ("cost",))

    harness.world.add_run([version.id], "cost", passed=True)
    _, missing, failed = await check(harness)
    assert (missing, failed) == ((), ())


async def test_runs_that_started_before_the_version_do_not_count(harness: Harness) -> None:
    version = harness.version()
    before = version.created_at - timedelta(seconds=1)
    for suite in REQUIRED_SUITES[KEY]:
        harness.world.add_run([version.id], suite, started_at=before)

    _, missing, failed = await check(harness)

    assert missing == REQUIRED_SUITES[KEY]
    assert failed == ()


async def test_runs_that_do_not_cover_the_version_or_did_not_finish_do_not_count(harness: Harness) -> None:
    await harness.seeder.sync(real_sources())
    version = harness.version()
    other = harness.world.versions_of("guard.input")[0]
    for suite in REQUIRED_SUITES[KEY]:
        harness.world.add_run([other.id], suite)
        harness.world.add_run([version.id], suite, status="running", passed=None)
        harness.world.add_run([version.id], suite, status="errored", passed=None)

    _, missing, failed = await check(harness)

    assert missing == REQUIRED_SUITES[KEY]
    assert failed == ()


async def test_one_run_can_cover_several_versions(harness: Harness) -> None:
    await harness.seeder.sync([source(body=CHANGED_BODY)])
    first, second = harness.version(1), harness.version(2)
    for suite in REQUIRED_SUITES[KEY]:
        harness.world.add_run([first.id, second.id], suite)

    for number in (1, 2):
        assert (await check(harness, number))[1:] == ((), ())


async def test_the_report_lists_the_passing_runs_of_every_required_suite(harness: Harness) -> None:
    harness.pass_suites()

    verdict = await harness.gate.check(AsyncSession(), harness.version().id)
    report = verdict.report()

    assert report["required"] == list(REQUIRED_SUITES[KEY])
    assert [entry["suite"] for entry in report["passed"]] == list(REQUIRED_SUITES[KEY])
    assert report["failed"] == [] == report["missing"]


async def test_an_unknown_version_is_not_found(harness: Harness) -> None:
    with pytest.raises(PromptVersionNotFoundError):
        await harness.gate.check(AsyncSession(), new_id())
