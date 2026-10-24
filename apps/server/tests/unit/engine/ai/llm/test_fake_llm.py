import json
from itertools import combinations
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import BaseModel
from tests.fakes.llm import InMemoryUsageLedger
from tests.unit.engine.ai.llm.support import FIXTURES_ROOT, RecordingTracer, context, make_call

from motionile.engine.ai.guardrails.decision import GuardDecision
from motionile.engine.ai.job_options import AspectName
from motionile.engine.ai.llm.config import StaticBudget
from motionile.engine.ai.llm.fake import FakeFixtureMissingError, FakeLlm, FakeScript
from motionile.engine.ai.llm.fake_planner import FixtureTooSmallError, planner_fixture_for
from motionile.engine.ai.llm.litellm_gateway import litellm
from motionile.engine.ai.llm.metadata import CallMetadataKey, join_aspects
from motionile.engine.ai.llm.models import (
    BudgetExceededError,
    LlmCall,
    LlmTask,
    LlmUnavailableError,
    LlmUsage,
    ModelOutputInvalidError,
)
from motionile.engine.ai.llm.outputs import SkillSelection, StoryboardCritique, VisionReview
from motionile.engine.ai.scenes.models import SceneModule
from motionile.engine.ai.storyboard import Storyboard, StoryboardExpectation, StoryboardLimits, validate_storyboard

DURATIONS_SECONDS = (10, 30, 60, 120)
TOPICS = ("how DNS works", "binary search", "photosynthesis", "an unrelated subject")
ASPECT_SETS: list[tuple[AspectName, ...]] = [
    subset for size in (1, 2, 3) for subset in combinations(("16:9", "9:16", "1:1"), size)
]


def fake_llm(
    root: Path = FIXTURES_ROOT,
    script: FakeScript | None = None,
    ledger: InMemoryUsageLedger | None = None,
    budget: int = 1_000_000,
) -> FakeLlm:
    return FakeLlm(
        fixtures_root=root,
        ledger=ledger or InMemoryUsageLedger(),
        budget=StaticBudget(budget),
        script=script,
    )


def plan_call(
    duration_s: int, aspects: tuple[AspectName, ...], topic: str | None = None, style: str = "whiteboard"
) -> LlmCall:
    metadata = {
        CallMetadataKey.DURATION_MS.value: str(duration_s * 1000),
        CallMetadataKey.ASPECTS.value: join_aspects(list(aspects)),
        CallMetadataKey.LANGUAGE.value: "en-IN",
        CallMetadataKey.STYLE.value: style,
    }
    if topic is not None:
        metadata[CallMetadataKey.TOPIC.value] = topic
    return make_call(LlmTask.PLAN, metadata=metadata)


@pytest.mark.parametrize("topic", TOPICS)
@pytest.mark.parametrize("duration_s", DURATIONS_SECONDS)
@pytest.mark.parametrize("aspects", ASPECT_SETS)
async def test_planner_storyboards_fit_the_request_for_every_duration_and_aspect_set(
    topic: str, duration_s: int, aspects: tuple[AspectName, ...]
) -> None:
    result = await fake_llm().generate(plan_call(duration_s, aspects, topic), Storyboard)

    storyboard = result.output
    expectation = StoryboardExpectation(duration_s * 1000, list(aspects), "en-IN", "whiteboard")
    assert validate_storyboard(storyboard, expectation, StoryboardLimits()) == []
    assert storyboard.target_duration_ms == duration_s * 1000
    assert abs(storyboard.scene_total_ms - duration_s * 1000) <= duration_s * 100
    assert set(storyboard.aspects) == set(aspects)
    assert 2 <= len(storyboard.scenes) <= 12
    for scene in storyboard.scenes:
        assert set(scene.layout_notes) == set(aspects)
        rate = scene.word_count / (scene.target_duration_ms / 1000)
        assert 2.0 <= rate <= 2.8


@pytest.mark.parametrize(
    ("topic", "title"),
    [
        ("How does DNS work?", "How DNS Works"),
        ("binary-search", "Binary Search in Twenty Steps"),
        ("Explain photosynthesis", "How Photosynthesis Works"),
        ("quantum gravity", "How to Explain Anything"),
    ],
)
async def test_the_planner_fixture_follows_the_topic(topic: str, title: str) -> None:
    result = await fake_llm().generate(plan_call(30, ("16:9",), topic), Storyboard)

    assert result.output.title == title


async def test_a_planner_call_without_a_topic_uses_the_generic_fixture() -> None:
    result = await fake_llm().generate(plan_call(30, ("16:9",)), Storyboard)

    assert result.output.title == "How to Explain Anything"


async def test_an_explicit_fixture_key_beats_the_topic() -> None:
    call = make_call(LlmTask.PLAN, metadata={"fixture": "dns", "topic": "photosynthesis", "durationMs": "30000"})

    result = await fake_llm().generate(call, Storyboard)

    assert result.output.title == "How DNS Works"


async def test_a_planner_call_without_metadata_still_returns_a_valid_storyboard() -> None:
    result = await fake_llm().generate(make_call(LlmTask.PLAN), Storyboard)

    issues = validate_storyboard(
        result.output, StoryboardExpectation(60_000, ["16:9"], "en", "minimal-dark"), StoryboardLimits()
    )
    assert issues == []


def test_planner_topics_are_recognised_by_keyword() -> None:
    assert planner_fixture_for("The DNS lookup chain") == "dns"
    assert planner_fixture_for(None) == "default"


async def test_a_fixture_that_cannot_fill_the_duration_is_reported(tmp_path: Path) -> None:
    (tmp_path / "plan").mkdir()
    source = json.loads((FIXTURES_ROOT / "plan" / "dns.json").read_text(encoding="utf-8"))
    for scene in source["scenes"]:
        scene["narration"] = "Short."
    (tmp_path / "plan" / "default.json").write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(FixtureTooSmallError):
        await fake_llm(tmp_path).generate(plan_call(60, ("16:9",)), Storyboard)


async def test_the_same_call_gives_identical_output_and_usage() -> None:
    call = plan_call(60, ("16:9", "9:16"), "binary search")

    first = await fake_llm().generate(call, Storyboard)
    second = await fake_llm().generate(call, Storyboard)

    assert first.output == second.output
    assert first.usage == second.usage
    assert first.usage.cost_micros_usd == 0
    assert first.usage.provider == "fake"


@pytest.mark.parametrize(
    ("task", "output"),
    [
        (LlmTask.CRITIQUE, StoryboardCritique),
        (LlmTask.VISION_REVIEW, VisionReview),
        (LlmTask.ROUTE, SkillSelection),
        (LlmTask.GUARD, GuardDecision),
    ],
)
async def test_the_default_fixture_of_each_task_validates(task: LlmTask, output: type[BaseModel]) -> None:
    result = await fake_llm().generate(make_call(task), output)

    assert result.attempts == 1


async def test_every_shipped_fixture_validates_against_its_output_model() -> None:
    expectations = {
        "guard": GuardDecision,
        "critique": StoryboardCritique,
        "review": VisionReview,
        "route": SkillSelection,
    }
    checked = 0
    for directory, model in expectations.items():
        for path in sorted((FIXTURES_ROOT / directory).glob("*.json")):
            model.model_validate_json(path.read_text(encoding="utf-8"))
            checked += 1
    for path in sorted((FIXTURES_ROOT / "plan").glob("*.json")):
        Storyboard.model_validate_json(path.read_text(encoding="utf-8"))
        checked += 1
    assert checked >= 15


async def test_guard_fixtures_are_selected_by_key_or_script() -> None:
    refuse = make_call(LlmTask.GUARD, metadata={"fixture": "refuse-weapons"})

    by_key = await fake_llm().generate(refuse, GuardDecision)
    by_script = await fake_llm(script=FakeScript().with_fixture(LlmTask.GUARD, "default", "refuse-malware")).generate(
        make_call(LlmTask.GUARD), GuardDecision
    )

    assert (by_key.output.verdict, by_key.output.code) == ("refuse", "policy_weapons")
    assert by_script.output.code == "policy_malware"


async def test_critique_attempts_can_be_scripted_per_task() -> None:
    script = FakeScript.for_task(LlmTask.CRITIQUE, ["blocking", "pass"])
    llm = fake_llm(script=script)

    first = await llm.generate(make_call(LlmTask.CRITIQUE), StoryboardCritique)
    second = await llm.generate(make_call(LlmTask.CRITIQUE), StoryboardCritique)
    third = await llm.generate(make_call(LlmTask.CRITIQUE), StoryboardCritique)

    assert [first.output.is_clean, second.output.is_clean, third.output.is_clean] == [False, True, True]
    assert first.output.blocking_issues[0].category == "pacing"


def write_scene_fixtures(root: Path) -> None:
    (root / "scene").mkdir()
    for name, builder in (("default", "ctx.at(0);"), ("broken-overflow", "ctx.at(1);")):
        module = {
            "version": 1,
            "sceneId": "{{sceneId}}",
            "builder": builder,
            "css": ".mo-s-{{sceneId}} { color: red; }",
        }
        (root / "scene" / f"{name}.json").write_text(json.dumps(module), encoding="utf-8")


async def test_a_scene_can_be_scripted_broken_first_and_good_on_repair(tmp_path: Path) -> None:
    write_scene_fixtures(tmp_path)
    script = FakeScript.for_scene("problem", ["broken-overflow", "default"])
    llm = fake_llm(tmp_path, script)
    scene_call = make_call(LlmTask.SCENE, metadata={"sceneId": "problem"})
    repair_call = make_call(LlmTask.REPAIR, metadata={"sceneId": "problem"})

    first = await llm.generate(scene_call, SceneModule)
    repaired = await llm.generate(repair_call, SceneModule)
    again = await llm.generate(repair_call, SceneModule)

    assert first.output.builder == "ctx.at(1);"
    assert repaired.output.builder == "ctx.at(0);"
    assert again.output.builder == "ctx.at(0);"


async def test_unscripted_scenes_use_the_default_fixture_and_get_their_own_id(tmp_path: Path) -> None:
    write_scene_fixtures(tmp_path)
    script = FakeScript.for_scene("problem", ["broken-overflow", "default"])
    llm = fake_llm(tmp_path, script)

    hook = await llm.generate(make_call(LlmTask.SCENE, metadata={"sceneId": "hook"}), SceneModule)
    other = await llm.generate(make_call(LlmTask.SCENE, metadata={"sceneId": "recap"}), SceneModule)

    assert hook.output.scene_id == "hook"
    assert hook.output.builder == "ctx.at(0);"
    assert hook.output.css == ".mo-s-hook { color: red; }"
    assert other.output.scene_id == "recap"


async def test_scene_scripts_compose_with_task_scripts(tmp_path: Path) -> None:
    write_scene_fixtures(tmp_path)
    script = FakeScript.for_scene("a", ["broken-overflow"]).with_scene("b", ["default"])
    llm = fake_llm(tmp_path, script)

    a = await llm.generate(make_call(LlmTask.SCENE, metadata={"sceneId": "a"}), SceneModule)
    b = await llm.generate(make_call(LlmTask.SCENE, metadata={"sceneId": "b"}), SceneModule)

    assert (a.output.builder, b.output.builder) == ("ctx.at(1);", "ctx.at(0);")


async def test_a_scripted_error_is_raised_and_records_no_usage() -> None:
    ledger = InMemoryUsageLedger()
    llm = fake_llm(script=FakeScript.for_task(LlmTask.PLAN, [LlmUnavailableError()]), ledger=ledger)

    with pytest.raises(LlmUnavailableError):
        await llm.generate(plan_call(30, ("16:9",)), Storyboard)

    assert ledger.records == []


async def test_a_fixture_that_breaks_the_schema_raises_model_output_invalid(tmp_path: Path) -> None:
    (tmp_path / "critique").mkdir()
    (tmp_path / "critique" / "pass.json").write_text('{"verdict": "maybe"}', encoding="utf-8")

    with pytest.raises(ModelOutputInvalidError):
        await fake_llm(tmp_path).generate(make_call(LlmTask.CRITIQUE), StoryboardCritique)


async def test_a_missing_fixture_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(FakeFixtureMissingError, match=r"critique/pass\.json"):
        await fake_llm(tmp_path).generate(make_call(LlmTask.CRITIQUE), StoryboardCritique)


async def test_usage_is_recorded_through_the_ledger_with_derived_keys() -> None:
    ledger = InMemoryUsageLedger()
    job_id = uuid4()
    call = make_call(LlmTask.GUARD, call_context=context(job_id, "job:guard"), user=("Explain DNS",))

    result = await fake_llm(ledger=ledger).generate(call, GuardDecision)

    assert ledger.keys == ["job:guard:0:fake/guard"]
    assert ledger.records[0].usage == result.usage
    assert await ledger.tokens_used(job_id) == result.usage.total_tokens > 0


async def test_the_job_budget_is_enforced_for_the_fake_too() -> None:
    ledger = InMemoryUsageLedger()
    job_id = uuid4()
    await ledger.record(context(job_id, "earlier"), LlmTask.PLAN, LlmUsage("fake", "fake/plan", 900, 100, 0, 0))
    call = make_call(LlmTask.GUARD, call_context=context(job_id, "job:guard"))

    with pytest.raises(BudgetExceededError):
        await fake_llm(ledger=ledger, budget=1_000).generate(call, GuardDecision)


async def test_the_fake_is_traced_like_the_real_client() -> None:
    tracer = RecordingTracer()
    llm = FakeLlm(fixtures_root=FIXTURES_ROOT, ledger=InMemoryUsageLedger(), budget=StaticBudget(10**6), tracer=tracer)

    await llm.generate(make_call(LlmTask.GUARD), GuardDecision)

    name, _, span = tracer.spans[0]
    assert name == "guard.plan"
    assert len(span.usages) == 1
    assert span.ended == 1


async def test_the_fake_never_touches_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    async def forbidden(**_: object) -> None:
        raise AssertionError("the fake reached for the network")

    monkeypatch.setattr(litellm, "acompletion", forbidden)
    monkeypatch.setattr(litellm, "aembedding", forbidden)

    result = await fake_llm().generate(plan_call(30, ("16:9",), "dns"), Storyboard)

    assert result.output.scenes


async def test_the_fake_records_the_calls_it_received() -> None:
    llm = fake_llm()
    call = make_call(LlmTask.GUARD)

    await llm.generate(call, GuardDecision)

    assert llm.calls == [call]
