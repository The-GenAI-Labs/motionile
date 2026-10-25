import pytest
from pydantic import ValidationError
from tests.unit.modules.prompts.support import ACTOR, BODY, KEY, Harness, build_harness

from motionile.engine.ai.prompts.loader import body_checksum
from motionile.modules.prompts.domain import MAX_BODY_CHARS
from motionile.modules.prompts.drafts import CANARY_LINE, validate_draft
from motionile.modules.prompts.exceptions import DraftExistsError, DraftInvalidError, PromptTemplateNotFoundError
from motionile.modules.prompts.schemas import DraftRequest

VALID = "Internal marker: {{ canary }}.\n\nPlan the storyboard in {{ language }} for {{ audience }}.\n"


@pytest.fixture
async def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    built = build_harness(monkeypatch)
    await built.seed()
    return built


def test_a_valid_body_keeps_its_variables_in_order_after_the_canary() -> None:
    draft = validate_draft(VALID, ["language", "audience"])

    assert draft.variables == ("canary", "language", "audience")
    assert draft.checksum == body_checksum(VALID)
    assert draft.body == VALID


def test_the_declaration_may_list_the_canary_explicitly() -> None:
    assert validate_draft(VALID, ["canary", "language", "audience"]).variables == ("canary", "language", "audience")


def test_a_missing_canary_line_is_appended() -> None:
    draft = validate_draft("Plan the storyboard in {{ language }}.", ["language"])

    assert draft.body.endswith(f"{CANARY_LINE}\n")
    assert draft.variables == ("canary", "language")


def test_undeclared_and_unused_variables_are_rejected() -> None:
    with pytest.raises(DraftInvalidError, match="Undeclared variables"):
        validate_draft(VALID, ["language"])
    with pytest.raises(DraftInvalidError, match="unused variables"):
        validate_draft(VALID, ["language", "audience", "tone"])


@pytest.mark.parametrize(
    "body",
    [
        "{{ canary }} {% if language %}",
        "{{ canary }} {{ language | nonexistent_filter }}",
        "{{ canary }} {{ language.__class__.__mro__ }}",
        "{{ canary }} {% include 'other' %}",
    ],
)
def test_templates_that_do_not_compile_or_render_in_the_sandbox_are_rejected(body: str) -> None:
    with pytest.raises(DraftInvalidError):
        validate_draft(body, ["language"])


def test_the_size_cap_applies_before_and_after_the_canary_line_is_appended() -> None:
    with pytest.raises(DraftInvalidError, match="longer than"):
        validate_draft("x" * (MAX_BODY_CHARS + 1) + "{{ canary }}", [])
    with pytest.raises(DraftInvalidError, match="longer than"):
        validate_draft("x" * (MAX_BODY_CHARS - 5), [])


def test_the_request_is_closed_stripped_and_bounded() -> None:
    assert DraftRequest.model_validate({"body": f"  {VALID}  ", "variables": ["language"]}).body == VALID.strip()
    assert DraftRequest.model_validate({"body": VALID}).variables == []
    for body in (
        {"body": "short"},
        {"body": "x" * (MAX_BODY_CHARS + 1)},
        {"body": VALID, "variables": ["Bad Name"]},
        {"body": VALID, "variables": ["a", "a"]},
        {"body": VALID, "variables": [f"v{index}" for index in range(33)]},
        {"body": VALID, "extra": 1},
    ):
        with pytest.raises(ValidationError):
            DraftRequest.model_validate(body)


async def test_a_draft_becomes_the_next_pending_version_with_a_fresh_canary(harness: Harness) -> None:
    request = DraftRequest(body=VALID, variables=["language", "audience"])

    view = await harness.service.create_draft(ACTOR, KEY, request)

    assert (view.version, view.eval_status.value, view.is_active, view.created_by) == (
        2,
        "pending",
        False,
        ACTOR.user_id,
    )
    stored = harness.version(2)
    assert stored.body == VALID
    assert list(stored.variables) == ["canary", "language", "audience"]
    assert 16 <= len(stored.canary) <= 64
    assert stored.canary != harness.version(1).canary
    [event] = [event for event in harness.audit if event.action == "prompts.draft_created" and event.actor_user_id]
    assert event.metadata["source"] == "admin"
    assert event.metadata["version"] == 2


async def test_a_draft_never_activates_anything(harness: Harness) -> None:
    await harness.service.create_draft(ACTOR, KEY, DraftRequest(body=VALID, variables=["language", "audience"]))

    assert harness.world.template_by_key(KEY).active_version_id is None


async def test_the_same_text_cannot_be_drafted_twice(harness: Harness) -> None:
    request = DraftRequest(body=BODY, variables=["language"])

    with pytest.raises(DraftExistsError) as raised:
        await harness.service.create_draft(ACTOR, KEY, request)

    assert raised.value.code == "prompt_version_exists"
    assert len(harness.world.versions_of(KEY)) == 1


async def test_drafting_for_an_unknown_template_is_not_found(harness: Harness) -> None:
    with pytest.raises(PromptTemplateNotFoundError):
        await harness.service.create_draft(ACTOR, "missing.template", DraftRequest(body=BODY, variables=["language"]))


async def test_an_invalid_draft_creates_nothing(harness: Harness) -> None:
    with pytest.raises(DraftInvalidError):
        await harness.service.create_draft(ACTOR, KEY, DraftRequest(body=VALID, variables=["language"]))

    assert len(harness.world.versions_of(KEY)) == 1
