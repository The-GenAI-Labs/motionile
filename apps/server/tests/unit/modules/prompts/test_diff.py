import json

import pytest
from fastapi.routing import APIRoute
from pydantic import TypeAdapter
from tests.unit.modules.prompts.support import ACTOR, BODY, CHANGED_BODY, KEY, Harness, build_harness, source

from motionile.modules.prompts import admin_prompts_router
from motionile.modules.prompts.diffing import REDACTED_LINE, diff_bodies, redacted_lines
from motionile.modules.prompts.exceptions import PromptTemplateNotFoundError, PromptVersionNotFoundError
from motionile.modules.prompts.repository import RunFilter

BANNED_FIELDS = {"body", "prompt", "canary", "text", "content", "lines", "instructions"}
DIFF_ROUTE = "diff_prompt_versions"


@pytest.fixture
async def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    built = build_harness(monkeypatch)
    await built.seed()
    await built.seeder.sync([source(body=CHANGED_BODY)])
    return built


def test_canary_references_and_literal_canaries_are_redacted() -> None:
    body = (
        "Intro\nInternal marker: {{ canary }}. Secret.\nValue mo-canary-abc123 leaked\n{%- if canary %}x{% endif %}\n"
    )

    assert redacted_lines(body, ["mo-canary-abc123"]) == ["Intro", REDACTED_LINE, REDACTED_LINE, REDACTED_LINE]


def test_the_diff_marks_added_and_removed_lines_and_counts_them() -> None:
    result = diff_bodies("a\nb\nc\n", "a\nB\nc\nd\n", [], older_label="v1", newer_label="v2")

    assert result.lines[:2] == ["--- v1", "+++ v2"]
    assert "-b" in result.lines
    assert "+B" in result.lines
    assert "+d" in result.lines
    assert (result.added, result.removed) == (2, 1)
    assert diff_bodies("a\n", "a\n", [], older_label="v1", newer_label="v2").lines == []


def test_a_removed_line_that_starts_with_dashes_is_still_counted() -> None:
    result = diff_bodies("-- sql\nkeep\n", "keep\n", [], older_label="v1", newer_label="v2")

    assert (result.added, result.removed) == (0, 1)


async def test_the_service_diff_never_contains_a_canary_or_its_reference(harness: Harness) -> None:
    older, newer = harness.version(1), harness.version(2)

    view = await harness.service.diff(ACTOR, KEY, 1, 2)

    joined = "\n".join(view.lines)
    assert older.canary not in joined
    assert newer.canary not in joined
    assert "{{ canary }}" not in joined
    assert "Plan a short storyboard" in joined
    assert (view.key, view.from_version, view.to_version) == (KEY, 1, 2)
    assert (view.added, view.removed) == (1, 1)


async def test_a_canary_pasted_into_a_body_is_redacted_too(harness: Harness) -> None:
    older = harness.version(1)
    older.body = f"{older.body}Leaked {older.canary} here.\n"

    view = await harness.service.diff(ACTOR, KEY, 1, 2)

    assert older.canary not in json.dumps(view.model_dump())


async def test_every_diff_is_audited(harness: Harness) -> None:
    await harness.service.diff(ACTOR, KEY, 1, 2)
    await harness.service.diff(ACTOR, KEY, 2, 1)

    events = [event for event in harness.audit if event.action == "prompts.diff_viewed"]
    assert [(event.metadata["from_version"], event.metadata["to_version"]) for event in events] == [(1, 2), (2, 1)]
    assert {event.actor_user_id for event in events} == {ACTOR.user_id}
    assert all(event.target_type == "prompt_template" for event in events)
    assert BODY.strip() not in json.dumps([event.metadata for event in events])


async def test_diffing_unknown_templates_or_versions_is_not_found_and_not_audited(harness: Harness) -> None:
    with pytest.raises(PromptTemplateNotFoundError):
        await harness.service.diff(ACTOR, "missing.template", 1, 2)
    with pytest.raises(PromptVersionNotFoundError):
        await harness.service.diff(ACTOR, KEY, 1, 7)

    assert not [event for event in harness.audit if event.action == "prompts.diff_viewed"]


def test_no_other_response_can_carry_prompt_text_or_canaries() -> None:
    routes = [route for route in admin_prompts_router.routes if isinstance(route, APIRoute)]
    assert len(routes) == 9
    for route in routes:
        if route.name == DIFF_ROUTE:
            continue
        dumped = json.dumps(TypeAdapter(route.response_model).json_schema())
        assert '"properties"' in dumped
        for banned in BANNED_FIELDS:
            assert f'"{banned}":' not in dumped, (route.name, banned)


async def test_listings_and_runs_never_serialize_bodies_or_canaries(harness: Harness) -> None:
    run = await harness.evals.start_run(ACTOR, "planner", [harness.version(1).id])
    listing = await harness.service.list_versions(KEY, None, 20)
    templates = await harness.service.list_templates()
    runs = await harness.evals.page(RunFilter(), None, 20)

    views = [run, *listing.items, *templates, *runs.items]
    dumped = json.dumps([view.model_dump(mode="json") for view in views])

    for version in harness.world.versions.values():
        assert version.canary not in dumped
        assert version.body.strip() not in dumped
