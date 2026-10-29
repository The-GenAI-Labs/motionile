from uuid import uuid4

import pytest

from evals.clients import FIXTURES_ROOT
from evals.datasets import load_datasets
from evals.metering import SpendLedger, SpendMeter
from evals.prompts import FilePromptStore
from evals.scripted import ScriptedLlm
from evals.scripted_plan import PlanRequest, generic_storyboard, scripted_storyboard
from motionile.engine.ai.guardrails.input_guard import InputGuard
from motionile.engine.ai.guardrails.policy import PolicyCode
from motionile.engine.ai.llm.metadata import CallMetadataKey
from motionile.engine.ai.llm.models import CallContext, LlmCall, LlmTask
from motionile.engine.ai.llm.outputs import SkillSelection
from motionile.engine.ai.prompts.delimit import delimit
from motionile.engine.ai.scenes.models import SceneModule
from motionile.engine.ai.storyboard import Storyboard, StoryboardExpectation, StoryboardLimits, validate_storyboard

DATASETS = load_datasets()
LIMITS = StoryboardLimits()


def scripted() -> tuple[ScriptedLlm, SpendLedger]:
    ledger = SpendLedger(SpendMeter())
    return ScriptedLlm(fixtures_root=FIXTURES_ROOT, ledger=ledger, datasets=DATASETS), ledger


def context(stage: str = "guard") -> CallContext:
    job = uuid4()
    return CallContext(user_id=uuid4(), job_id=job, stage=stage, call_key=f"{job}:{stage}")


def issues_of(board_request: PlanRequest, board: Storyboard) -> list[str]:
    expectation = StoryboardExpectation(
        duration_ms=board_request.duration_ms,
        aspects=board_request.aspects,
        language=board_request.language,
        style=board_request.style,
    )
    return [issue.code.value for issue in validate_storyboard(board, expectation, LIMITS)]


@pytest.mark.parametrize("case_id", [case.id for case in DATASETS.golden.cases])
def test_every_scripted_golden_storyboard_satisfies_the_deterministic_validator(case_id: str) -> None:
    case = DATASETS.golden_cases([case_id])[0]
    request = PlanRequest(case.duration_ms, case.aspects, case.language, "minimal-dark")

    assert issues_of(request, scripted_storyboard(case, request)) == []


@pytest.mark.parametrize("case_id", [case.id for case in DATASETS.duration.cases])
def test_every_scripted_generic_storyboard_satisfies_the_deterministic_validator(case_id: str) -> None:
    case = DATASETS.duration_cases([case_id])[0]
    request = PlanRequest(case.duration_ms, case.aspects, "en", "minimal-dark")

    assert issues_of(request, generic_storyboard(case.query, request)) == []


async def test_the_scripted_guard_follows_the_dataset_when_the_rules_do_not_decide() -> None:
    llm, _ = scripted()
    prompts = FilePromptStore()
    guard = InputGuard(llm, prompts)
    refused = next(case for case in DATASETS.adversarial.cases if case.id == "weapons-01")
    allowed = next(case for case in DATASETS.adversarial.cases if case.id == "allow-science-01")

    refusal = await guard.check(refused.text, context(), refused.kind)
    allowance = await guard.check(allowed.text, context(), allowed.kind)

    assert refusal.code is PolicyCode.WEAPONS
    assert allowance.allowed


async def test_the_scripted_guard_allows_text_it_does_not_know() -> None:
    llm, _ = scripted()

    result = await InputGuard(llm, FilePromptStore()).check("Explain how rainbows form", context(), "query")

    assert result.allowed


async def test_scripted_answers_are_recorded_in_the_ledger_with_tokens() -> None:
    llm, ledger = scripted()

    await InputGuard(llm, FilePromptStore()).check("Explain how rainbows form", context(), "query")

    assert len(ledger.records) == 1
    assert ledger.records[0].usage.total_tokens > 0
    assert ledger.records[0].usage.cost_micros_usd > 0


async def test_the_scripted_router_picks_the_listed_candidates_and_the_requested_style() -> None:
    llm, _ = scripted()
    listing = "\n".join(
        [
            "Style requested by the user: blueprint",
            "",
            "Candidates, Style layer",
            "- blueprint | Blueprint | cost 10 tokens | similarity n/a | x",
            "",
            "Candidates, Visual layer",
            "- flow-diagram | Flow | cost 10 tokens | similarity 0.50 | x",
            "- kinetic-typography | Kinetic | cost 10 tokens | similarity 0.40 | x",
            "- comparison-split | Split | cost 10 tokens | similarity 0.30 | x",
            "",
            "Candidates, Domain layer",
            "- backend | Backend | cost 10 tokens | similarity 0.50 | x",
            "- devops | DevOps | cost 10 tokens | similarity 0.40 | x",
        ]
    )
    call = LlmCall(LlmTask.ROUTE, context("context"), ["rules"], [delimit("context", listing)])

    selection = (await llm.generate(call, SkillSelection)).output

    assert selection.style.slug == "blueprint"
    assert [choice.slug for choice in selection.visual] == ["flow-diagram", "kinetic-typography"]
    assert [choice.slug for choice in selection.domain] == ["backend"]


def scene_call(task: LlmTask, position: int) -> LlmCall:
    block = delimit("context", f"sceneId: scene-{position + 1}\nposition: {position}\nsceneCount: 6")
    metadata = {CallMetadataKey.SCENE_ID.value: f"scene-{position + 1}"}
    return LlmCall(task, context("scenes"), ["rules"], [block], metadata)


async def test_scripted_scenes_rotate_fixtures_and_inject_a_defect_every_fifth_scene() -> None:
    llm, _ = scripted()

    first = (await llm.generate(scene_call(LlmTask.SCENE, 0), SceneModule)).output
    broken = (await llm.generate(scene_call(LlmTask.SCENE, 4), SceneModule)).output
    repaired = (await llm.generate(scene_call(LlmTask.REPAIR, 4), SceneModule)).output

    assert first.scene_id == "scene-1"
    assert broken.builder != repaired.builder
    assert broken.scene_id == repaired.scene_id == "scene-5"
