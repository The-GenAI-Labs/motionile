from uuid import UUID

import pytest
from tests.fakes.prompts import InMemoryPromptRepository
from tests.unit.modules.prompts.support import ACTOR, BODY, CHANGED_BODY, KEY, Harness, build_harness, source

from motionile.core.ids import new_id
from motionile.modules.prompts.domain import ActivationEvent, ActivationKind, previous_version_id
from motionile.modules.prompts.exceptions import (
    ActivationBlockedError,
    ActivationConflictError,
    NoPreviousVersionError,
    PromptNotActiveError,
    PromptTemplateNotFoundError,
    PromptVersionNotFoundError,
)
from motionile.modules.prompts.gate import REQUIRED_SUITES


@pytest.fixture
async def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    built = build_harness(monkeypatch)
    await built.seed()
    return built


async def add_versions(harness: Harness, count: int) -> None:
    bodies = [f"{CHANGED_BODY}Revision {index}.\n" for index in range(2, count + 1)]
    for body in bodies:
        await harness.seeder.sync([source(body=body)])
    for number in range(1, count + 1):
        harness.pass_suites(number)


def active_number(harness: Harness) -> int | None:
    active = harness.world.template_by_key(KEY).active_version_id
    return harness.world.versions[active].version if active is not None else None


async def test_activation_is_blocked_with_the_missing_suites(harness: Harness) -> None:
    harness.world.add_run([harness.version().id], "planner")

    with pytest.raises(ActivationBlockedError) as raised:
        await harness.service.activate(ACTOR, KEY, 1)

    assert raised.value.code == "activation_blocked"
    assert raised.value.status_code == 409
    assert raised.value.missing == ("safety", "cost")
    assert raised.value.extensions == {"missingSuites": "safety,cost", "failedSuites": ""}
    assert active_number(harness) is None
    assert harness.version().eval_status == "pending"


async def test_activation_is_blocked_by_a_failed_suite(harness: Harness) -> None:
    version = harness.version()
    harness.world.pass_all(KEY, ("planner", "safety"))
    harness.world.add_run([version.id], "cost", passed=False)

    with pytest.raises(ActivationBlockedError) as raised:
        await harness.service.activate(ACTOR, KEY, 1)

    assert (raised.value.missing, raised.value.failed) == ((), ("cost",))


async def test_a_passing_version_activates_and_records_the_evidence(harness: Harness) -> None:
    harness.pass_suites()

    view = await harness.service.activate(ACTOR, KEY, 1)

    assert (view.version, view.is_active, view.eval_status.value) == (1, True, "passed")
    stored = harness.version()
    assert stored.eval_status == "passed"
    assert stored.eval_report is not None
    assert stored.eval_report["required"] == list(REQUIRED_SUITES[KEY])
    assert active_number(harness) == 1
    [event] = [event for event in harness.audit if event.action == "prompts.version_activated"]
    assert event.actor_user_id == ACTOR.user_id
    assert event.metadata["version"] == 1
    assert event.metadata["from_version_id"] is None
    assert len(event.metadata["eval_run_ids"]) == len(REQUIRED_SUITES[KEY])


async def test_activating_the_active_version_again_changes_nothing(harness: Harness) -> None:
    harness.pass_suites()
    await harness.service.activate(ACTOR, KEY, 1)
    audited = len(harness.audit)

    view = await harness.service.activate(ACTOR, KEY, 1)

    assert view.is_active
    assert len(harness.audit) == audited


async def test_unknown_templates_and_versions_are_not_found(harness: Harness) -> None:
    with pytest.raises(PromptTemplateNotFoundError):
        await harness.service.activate(ACTOR, "missing.template", 1)
    with pytest.raises(PromptVersionNotFoundError):
        await harness.service.activate(ACTOR, KEY, 9)
    with pytest.raises(PromptTemplateNotFoundError):
        await harness.service.rollback(ACTOR, "missing.template")


async def test_a_concurrent_activation_loses_the_conditional_update(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    await add_versions(harness, 2)
    original = InMemoryPromptRepository.set_active

    async def raced(self: InMemoryPromptRepository, template_id: UUID, version_id: UUID, expected: UUID | None) -> bool:
        harness.world.templates[template_id].active_version_id = harness.version(2).id
        return await original(self, template_id, version_id, expected)

    monkeypatch.setattr(InMemoryPromptRepository, "set_active", raced)

    with pytest.raises(ActivationConflictError):
        await harness.service.activate(ACTOR, KEY, 1)

    assert active_number(harness) == 2


async def test_rollback_walks_back_through_the_activation_history(harness: Harness) -> None:
    await add_versions(harness, 3)
    for number in (1, 2, 3):
        await harness.service.activate(ACTOR, KEY, number)

    first = await harness.service.rollback(ACTOR, KEY)
    second = await harness.service.rollback(ACTOR, KEY)

    assert (first.version, second.version) == (2, 1)
    assert active_number(harness) == 1
    with pytest.raises(NoPreviousVersionError):
        await harness.service.rollback(ACTOR, KEY)
    assert [event.action for event in harness.audit if event.action.endswith("rolled_back")] == [
        "prompts.version_rolled_back"
    ] * 2


async def test_activating_after_a_rollback_continues_from_the_rolled_back_version(harness: Harness) -> None:
    await add_versions(harness, 3)
    await harness.service.activate(ACTOR, KEY, 1)
    await harness.service.activate(ACTOR, KEY, 2)
    await harness.service.rollback(ACTOR, KEY)

    await harness.service.activate(ACTOR, KEY, 3)
    rolled = await harness.service.rollback(ACTOR, KEY)

    assert rolled.version == 1


async def test_rollback_needs_an_active_version_and_a_history(harness: Harness) -> None:
    with pytest.raises(NoPreviousVersionError):
        await harness.service.rollback(ACTOR, KEY)

    harness.pass_suites()
    await harness.service.activate(ACTOR, KEY, 1)
    with pytest.raises(NoPreviousVersionError):
        await harness.service.rollback(ACTOR, KEY)


async def test_rollback_does_not_need_a_new_evaluation(harness: Harness) -> None:
    await add_versions(harness, 2)
    await harness.service.activate(ACTOR, KEY, 1)
    await harness.service.activate(ACTOR, KEY, 2)
    harness.world.runs.clear()

    view = await harness.service.rollback(ACTOR, KEY)

    assert view.version == 1


async def test_switching_the_active_version_refreshes_the_store_after_commit(harness: Harness) -> None:
    await add_versions(harness, 2)
    with pytest.raises(PromptNotActiveError):
        await harness.store.active(KEY)
    await harness.service.activate(ACTOR, KEY, 1)
    assert (await harness.store.active(KEY)).version == 1

    await harness.service.activate(ACTOR, KEY, 2)

    assert (await harness.store.active(KEY)).version == 2
    await harness.service.rollback(ACTOR, KEY)
    assert (await harness.store.active(KEY)).version == 1


def test_the_previous_version_is_derived_from_activation_events() -> None:
    first, second, third = new_id(), new_id(), new_id()
    activated = ActivationKind.ACTIVATED
    rolled_back = ActivationKind.ROLLED_BACK

    assert previous_version_id([], first) is None
    assert previous_version_id([ActivationEvent(activated, None, first)], first) is None
    chain = [ActivationEvent(activated, None, first), ActivationEvent(activated, first, second)]
    assert previous_version_id(chain, second) == first
    assert previous_version_id(chain, first) is None
    chain.append(ActivationEvent(activated, second, third))
    assert previous_version_id(chain, third) == second
    chain.append(ActivationEvent(rolled_back, third, second))
    assert previous_version_id(chain, second) == first
    chain.append(ActivationEvent(rolled_back, second, first))
    assert previous_version_id(chain, first) is None
    assert previous_version_id(chain, third) is None


async def test_listing_shows_the_active_flag_and_never_the_text(harness: Harness) -> None:
    await add_versions(harness, 2)
    await harness.service.activate(ACTOR, KEY, 2)

    listing = await harness.service.list_versions(KEY, None, 20)
    templates = await harness.service.list_templates()

    assert [(item.version, item.is_active) for item in listing.items] == [(2, True), (1, False)]
    assert all(len(item.checksum_prefix) == 12 for item in listing.items)
    [summary] = templates
    assert (summary.key, summary.active_version, summary.version_count) == (KEY, 2, 2)
    dumped = " ".join(item.model_dump_json() for item in listing.items) + summary.model_dump_json()
    assert BODY.strip() not in dumped
    assert all(version.canary not in dumped for version in harness.world.versions.values())


async def test_the_version_list_pages_with_a_cursor(harness: Harness) -> None:
    await add_versions(harness, 3)

    first = await harness.service.list_versions(KEY, None, 2)
    assert first.next_cursor is not None
    second = await harness.service.list_versions(KEY, first.next_cursor, 2)

    assert [item.version for item in first.items] == [3, 2]
    assert [item.version for item in second.items] == [1]
    assert second.next_cursor is None
