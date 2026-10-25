import json

from tests.unit.engine.ai.graphs.support import SCENE_COUNT_FOR_THIRTY_SECONDS, build_harness

from motionile.engine.ai.graphs.events import ALLOWED_PAYLOAD_KEYS, EventType
from motionile.engine.ai.graphs.run import RunOutcome
from motionile.engine.ai.job_options import JobStatus
from motionile.engine.ai.llm.models import LlmTask
from motionile.engine.ai.ports import SceneAttemptKind, StoryboardOrigin

EXPECTED_STAGES = [
    "guard",
    "context",
    "plan",
    "critique",
    "approval",
    "voice",
    "scenes",
    "compose",
    "validate",
    "visual_review",
    "render",
    "finalize",
]


async def test_a_job_without_review_runs_every_node_in_order_and_completes() -> None:
    harness = build_harness()

    outcome = await harness.run()

    assert outcome is RunOutcome.FINISHED
    assert harness.store.job.status is JobStatus.COMPLETED
    assert harness.store.stage_names == EXPECTED_STAGES
    assert harness.store.failure is None


async def test_the_model_is_called_once_per_responsibility() -> None:
    harness = build_harness()

    await harness.run()

    assert harness.tasks == {
        LlmTask.GUARD: 2,
        LlmTask.PLAN: 1,
        LlmTask.CRITIQUE: 1,
        LlmTask.SCENE: SCENE_COUNT_FOR_THIRTY_SECONDS,
        LlmTask.VISION_REVIEW: SCENE_COUNT_FOR_THIRTY_SECONDS,
    }


async def test_the_storyboard_is_stored_approved_voiced_and_every_scene_has_a_module() -> None:
    harness = build_harness()

    await harness.run()

    store = harness.store
    assert store.origins == [StoryboardOrigin.PLANNER]
    assert len(store.storyboards) == 1
    assert store.storyboards[0].id in store.approved_ids
    assert store.narration_document is not None
    assert [scene.id for scene in store.narration_document.scenes] == harness.storyboard_ids()
    assert [saved.kind for saved in store.saved_modules] == [SceneAttemptKind.INITIAL] * SCENE_COUNT_FOR_THIRTY_SECONDS
    assert len(harness.narrator.calls) == 1


async def test_the_render_starts_once_with_the_composition_and_the_job_completes_with_the_narration_duration() -> None:
    harness = build_harness()

    await harness.run()

    assert len(harness.renders.started) == 1
    assert harness.store.job.render_id == harness.renders.render_id
    assert harness.store.narration_document is not None
    assert harness.store.completed_duration_ms == harness.store.narration_document.total_duration_ms
    started_html = harness.renders.started[0][1]
    assert started_html == harness.checker.checked_html[-1]


async def test_the_status_follows_the_state_machine() -> None:
    harness = build_harness()

    await harness.run()

    distinct = [
        status
        for index, (status, _) in enumerate(harness.store.stages)
        if index == 0 or status != harness.store.stages[index - 1][0]
    ]
    assert distinct == [
        JobStatus.PLANNING,
        JobStatus.VOICING,
        JobStatus.GENERATING,
        JobStatus.VALIDATING,
        JobStatus.RENDERING,
    ]


async def test_events_follow_the_documented_order() -> None:
    harness = build_harness()

    await harness.run()

    types = [event_type for event_type in harness.store.event_types if not event_type.startswith("stage.")]
    assert types[:4] == ["guard.passed", "context.ready", "storyboard.ready", "critique.completed"]
    voiced = types.index("scene.voiced")
    generated = types.index("scene.generated")
    assert types.index("critique.completed") < voiced < generated
    assert types.count("scene.voiced") == SCENE_COUNT_FOR_THIRTY_SECONDS
    assert types.count("scene.generated") == SCENE_COUNT_FOR_THIRTY_SECONDS
    assert types.index("validation.completed") < types.index("review.completed") < types.index("render.progress")
    assert types[-1] == "job.completed"


async def test_every_event_carries_only_the_documented_keys() -> None:
    harness = build_harness()

    await harness.run()

    allowed = {event_type.value: keys for event_type, keys in ALLOWED_PAYLOAD_KEYS.items()}
    for event in harness.store.events:
        if event.type in allowed:
            assert set(event.payload) <= allowed[event.type], event.type


async def test_every_stage_completion_follows_its_start() -> None:
    harness = build_harness()

    await harness.run()

    stage_events = [
        (event.type, event.payload["stage"]) for event in harness.store.events if event.type.startswith("stage.")
    ]
    assert stage_events == [
        (kind, stage) for stage in EXPECTED_STAGES for kind in (EventType.STAGE_STARTED, EventType.STAGE_COMPLETED)
    ]
    assert all(
        isinstance(event.payload["durationMs"], int)
        for event in harness.store.events_of(EventType.STAGE_COMPLETED.value)
    )


async def test_the_plan_call_carries_the_job_parameters_for_the_fake_planner() -> None:
    harness = build_harness()

    await harness.run()

    (plan,) = harness.llm.calls_of(LlmTask.PLAN)
    assert plan.metadata["durationMs"] == "30000"
    assert plan.metadata["aspects"] == "16:9"
    assert plan.metadata["language"] == "en"
    assert plan.metadata["style"] == "minimal-dark"
    assert plan.metadata["topic"].startswith("How does binary search")


async def test_no_prompt_text_canary_or_skill_text_reaches_events_or_errors() -> None:
    harness = build_harness()
    await harness.run()
    payloads = json.dumps([[event.type, dict(event.payload)] for event in harness.store.events])
    leaked = [prompt.canary for prompt in harness.prompts.prompts.values() if prompt.canary in payloads]
    skills = [skill.body for skill in harness.router.selected.all if skill.body in payloads]

    assert leaked == []
    assert skills == []
    assert "Internal marker" not in payloads
