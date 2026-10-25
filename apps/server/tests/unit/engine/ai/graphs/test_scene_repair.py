from tests.fakes.pipeline import (
    always_broken,
    broken_on_checks,
    broken_until_fallback,
    make_job,
    scene_issue,
)
from tests.scene_support import load_scene_fixture
from tests.unit.engine.ai.graphs.support import Harness, build_harness

from motionile.engine.ai.graphs.deps import PipelineConfig
from motionile.engine.ai.graphs.run import RunOutcome
from motionile.engine.ai.llm.fake import FakeScript
from motionile.engine.ai.llm.models import LlmTask, LlmUnavailableError, ModelOutputInvalidError
from motionile.engine.ai.ports import SceneAttemptKind
from motionile.engine.ai.scenes.models import SceneModule
from motionile.engine.ai.scenes.static_checks import check_scene_module
from motionile.engine.render.models import RenderEngineError

SCENE_IDS = ["hook", "example", "recap"]
TARGET = "example"


def kinds_for(harness: Harness, scene_id: str) -> list[SceneAttemptKind]:
    return [saved.kind for saved in harness.store.saved_modules if saved.scene_id == scene_id]


async def test_the_fixture_plan_has_the_scene_ids_these_tests_rely_on() -> None:
    harness = build_harness()

    await harness.run()

    assert harness.storyboard_ids() == SCENE_IDS


async def test_a_statically_broken_module_is_re_asked_once_through_the_repair_prompt_before_it_is_stored() -> None:
    script = FakeScript.for_scene(TARGET, ["broken-syntax", "default"])
    harness = build_harness(script=script)

    outcome = await harness.run()

    assert outcome is RunOutcome.FINISHED
    assert harness.tasks[LlmTask.SCENE] == len(SCENE_IDS)
    assert harness.tasks[LlmTask.REPAIR] == 1
    (reask,) = harness.llm.calls_of(LlmTask.REPAIR)
    blocks = [str(block) for block in reask.user_blocks]
    assert any("attempt: 1" in block for block in blocks)
    assert any(block.startswith("<previous_attempt>") for block in blocks)
    assert any(block.startswith("<issues>") and "builder_syntax" in block for block in blocks)
    assert kinds_for(harness, TARGET) == [SceneAttemptKind.INITIAL]
    assert harness.store.records[TARGET].attempts == 0


async def test_static_findings_never_reach_the_composition() -> None:
    script = FakeScript.for_scene(TARGET, ["broken-forbidden-api", "broken-unscoped-css", "default"])
    harness = build_harness(script=script)

    await harness.run()

    broken = load_scene_fixture("broken-forbidden-api", TARGET).builder
    for html in harness.checker.checked_html:
        assert broken not in html
    assert all(
        record.module is not None and check_scene_module(record.module) == []
        for record in harness.store.records.values()
    )


async def test_a_module_that_is_still_broken_after_the_re_ask_goes_to_repair_before_composition() -> None:
    script = FakeScript.for_scene(TARGET, ["broken-unscoped-css", "broken-unscoped-css", "default"])
    harness = build_harness(script=script)

    outcome = await harness.run()

    assert outcome is RunOutcome.FINISHED
    stages = harness.store.stage_names
    assert stages[stages.index("scenes") + 1] == "repair"
    assert stages.index("repair") < stages.index("compose")
    assert kinds_for(harness, TARGET) == [SceneAttemptKind.INITIAL, SceneAttemptKind.REPAIR]
    (repaired,) = harness.store.events_of("scene.repaired")
    assert repaired.payload == {"sceneId": TARGET, "attempt": 1, "issueCodes": ["css_unscoped"]}
    assert len(harness.checker.checked_html) == 1


async def test_a_scene_that_never_gets_clean_is_replaced_by_its_fallback_after_the_maximum_repairs() -> None:
    script = FakeScript.for_scene(TARGET, ["broken-syntax"])
    harness = build_harness(script=script)

    outcome = await harness.run()

    assert outcome is RunOutcome.FINISHED
    assert harness.tasks[LlmTask.SCENE] == len(SCENE_IDS)
    assert harness.tasks[LlmTask.REPAIR] == 3
    assert kinds_for(harness, TARGET) == [
        SceneAttemptKind.INITIAL,
        SceneAttemptKind.REPAIR,
        SceneAttemptKind.REPAIR,
        SceneAttemptKind.FALLBACK,
    ]
    assert harness.store.records[TARGET].is_fallback
    assert harness.store.records[TARGET].attempts == 2
    (fallback,) = harness.store.events_of("scene.fallback")
    assert fallback.payload == {"sceneId": TARGET, "reason": "repairs_exhausted"}
    (completed,) = harness.store.events_of("job.completed")
    assert completed.payload["fallbackSceneIds"] == [TARGET]


async def test_the_repair_limit_comes_from_the_configuration() -> None:
    script = FakeScript.for_scene(TARGET, ["broken-syntax"])
    harness = build_harness(script=script, config=PipelineConfig(max_repairs=0, render_poll_seconds=0.001))

    await harness.run()

    assert harness.tasks[LlmTask.REPAIR] == 1
    assert kinds_for(harness, TARGET) == [SceneAttemptKind.INITIAL, SceneAttemptKind.FALLBACK]


async def test_a_sandbox_issue_sends_only_that_scene_to_repair_and_the_loop_ends_when_it_is_clean() -> None:
    harness = build_harness(rules=[broken_on_checks(TARGET, {0})])

    outcome = await harness.run()

    assert outcome is RunOutcome.FINISHED
    assert harness.tasks[LlmTask.REPAIR] == 1
    assert [call.metadata["sceneId"] for call in harness.llm.calls_of(LlmTask.REPAIR)] == [TARGET]
    stages = harness.store.stage_names
    assert stages.count("repair") == 1
    assert stages.count("compose") == 2
    assert stages.count("validate") == 2
    assert len(harness.checker.checked_html) == 2
    assert kinds_for(harness, TARGET) == [SceneAttemptKind.INITIAL, SceneAttemptKind.REPAIR]
    assert [saved.issue_codes for saved in harness.store.saved_modules if saved.kind is SceneAttemptKind.REPAIR] == [
        ("text_overflow",)
    ]
    validation = harness.store.events_of("validation.completed")[0]
    assert validation.payload == {"errors": 1, "warnings": 0}


async def test_the_repair_prompt_carries_the_failed_module_and_the_issues_as_data() -> None:
    harness = build_harness(rules=[broken_on_checks(TARGET, {0})])

    await harness.run()

    (repair,) = harness.llm.calls_of(LlmTask.REPAIR)
    blocks = [str(block) for block in repair.user_blocks]
    assert blocks[0].startswith("<context>")
    assert "sceneId: example" in blocks[0]
    assert "attempt: 1" in blocks[0]
    assert blocks[1].startswith("<narration>")
    assert blocks[2].startswith("<previous_attempt>")
    assert '"builder"' in blocks[2]
    assert '"css"' in blocks[2]
    assert blocks[3].startswith("<issues>")
    assert "text_overflow" in blocks[3]
    assert '"kind":"layout"' in blocks[3]


async def test_a_scene_that_fails_every_time_ends_as_a_fallback_and_the_job_still_completes() -> None:
    harness = build_harness(rules=[broken_until_fallback(TARGET)])

    outcome = await harness.run()

    assert outcome is RunOutcome.FINISHED
    assert harness.tasks[LlmTask.REPAIR] == 2
    assert kinds_for(harness, TARGET)[-1] is SceneAttemptKind.FALLBACK
    assert len(harness.checker.checked_html) == 4
    assert len(harness.store.events_of("scene.repaired")) == 2
    assert len(harness.store.events_of("scene.fallback")) == 1
    assert harness.store.completed_duration_ms is not None


async def test_a_fallback_that_still_has_blocking_issues_fails_the_job() -> None:
    harness = build_harness(rules=[always_broken(TARGET)])

    outcome = await harness.run()

    assert outcome is RunOutcome.FAILED
    assert harness.store.failure is not None
    assert harness.store.failure[0] == "composition_invalid"
    assert harness.renders.started == []


async def test_a_document_level_issue_sends_every_scene_to_repair() -> None:
    harness = build_harness(rules=[lambda _html, index: [scene_issue(None, "html_too_large")] if index == 0 else []])

    outcome = await harness.run()

    assert outcome is RunOutcome.FINISHED
    assert harness.tasks[LlmTask.REPAIR] == len(SCENE_IDS)
    assert len(harness.store.events_of("scene.repaired")) == len(SCENE_IDS)


async def test_an_invalid_model_answer_for_a_scene_falls_back_instead_of_failing() -> None:
    script = FakeScript.for_scene(TARGET, [ModelOutputInvalidError()])
    harness = build_harness(script=script)

    outcome = await harness.run()

    assert outcome is RunOutcome.FINISHED
    assert kinds_for(harness, TARGET) == [SceneAttemptKind.FALLBACK]
    (fallback,) = harness.store.events_of("scene.fallback")
    assert fallback.payload["reason"] == "model_output_invalid"


async def test_the_scene_id_in_the_module_is_overwritten_with_the_storyboard_id() -> None:
    wrong = SceneModule(
        scene_id="elsewhere",
        builder="ctx.timeline.from(ctx.root, { opacity: 0 }, 0);",
        css=".mo-s-elsewhere { display: flex; }",
    )
    harness = build_harness(overrides={LlmTask.SCENE: [wrong]})

    outcome = await harness.run()

    assert outcome is RunOutcome.FINISHED
    assert set(harness.store.records) == set(SCENE_IDS)
    assert all(
        record.module is not None and record.module.scene_id == record.scene_id
        for record in harness.store.records.values()
    )
    assert harness.tasks[LlmTask.REPAIR] == 1


async def test_a_canary_in_scene_code_fails_the_job_as_blocked_output() -> None:
    harness = build_harness()
    canary = harness.prompts.prompts["scene.module"].canary
    harness.llm.script(LlmTask.SCENE, SceneModule(scene_id="hook", builder=f"ctx.root.dataset.note = '{canary}';"))

    outcome = await harness.run()

    assert outcome is RunOutcome.FAILED
    assert harness.store.failure is not None
    assert harness.store.failure[0] == "output_blocked"
    assert canary not in harness.store.failure[1]
    assert harness.renders.started == []


async def test_a_blocking_visual_review_issue_triggers_a_repair_and_only_that_scene_is_reviewed_again() -> None:
    script = FakeScript.for_task(LlmTask.VISION_REVIEW, ["legibility", "clean"])
    harness = build_harness(script=script)

    outcome = await harness.run()

    assert outcome is RunOutcome.FINISHED
    assert harness.tasks[LlmTask.VISION_REVIEW] == len(SCENE_IDS) + 1
    (repaired,) = harness.store.events_of("scene.repaired")
    assert repaired.payload == {"sceneId": "hook", "attempt": 1, "issueCodes": ["review_legibility"]}
    assert harness.store.stage_names.count("visual_review") == 2
    assert harness.store.review_report["issues"] == []


async def test_a_failed_review_call_is_recorded_and_skipped() -> None:
    harness = build_harness(overrides={LlmTask.VISION_REVIEW: [LlmUnavailableError()]})

    outcome = await harness.run()

    assert outcome is RunOutcome.FINISHED
    assert harness.store.review_report["skipped"] == [{"sceneId": "hook", "code": "llm_unavailable"}]
    assert harness.tasks[LlmTask.REPAIR] == 0


async def test_a_sampling_failure_skips_the_review_without_failing_the_job() -> None:
    harness = build_harness()
    harness.checker.sample_failure = RenderEngineError("sandbox down")

    outcome = await harness.run()

    assert outcome is RunOutcome.FINISHED
    assert harness.tasks[LlmTask.VISION_REVIEW] == 0
    skipped = harness.store.review_report["skipped"]
    assert isinstance(skipped, list)
    assert len(skipped) == len(SCENE_IDS)


async def test_the_review_can_be_switched_off() -> None:
    harness = build_harness(config=PipelineConfig(visual_review_enabled=False, render_poll_seconds=0.001))

    outcome = await harness.run()

    assert outcome is RunOutcome.FINISHED
    assert harness.tasks[LlmTask.VISION_REVIEW] == 0
    assert "visual_review" not in harness.store.stage_names
    assert harness.checker.sampled_html == []


async def test_scenes_with_blocking_validation_issues_skip_the_review_until_they_are_repaired() -> None:
    harness = build_harness(rules=[broken_on_checks(TARGET, {0})])

    await harness.run()

    assert harness.store.stage_names.count("visual_review") == 1
    assert harness.tasks[LlmTask.VISION_REVIEW] == len(SCENE_IDS)


async def test_the_job_options_do_not_change_the_scene_context() -> None:
    harness = build_harness(job=make_job(duration_seconds=30, aspects=("16:9", "9:16")))

    await harness.run()

    context = str(harness.llm.calls_of(LlmTask.SCENE)[0].user_blocks[0])
    assert "aspects: 16:9, 9:16" in context
    assert "style: minimal-dark" in context
    assert "language: en" in context
