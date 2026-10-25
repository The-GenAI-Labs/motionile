import json
from dataclasses import replace

import pytest
from tests.fakes.pipeline import make_job
from tests.unit.engine.ai.graphs.support import build_harness

from motionile.engine.ai.graphs.deps import PipelineConfig
from motionile.engine.ai.graphs.run import RunOutcome
from motionile.engine.ai.llm.fake import FakeScript
from motionile.engine.ai.llm.models import LlmTask
from motionile.engine.ai.prompts.canary import OutputScanner


@pytest.mark.parametrize("limit", [1, 2, 3])
async def test_scene_generation_never_exceeds_the_configured_concurrency(limit: int) -> None:
    harness = build_harness(
        job=make_job(duration_seconds=60),
        config=PipelineConfig(scene_concurrency=limit, render_poll_seconds=0.001),
    )

    outcome = await harness.run()

    assert outcome is RunOutcome.FINISHED
    assert harness.tasks[LlmTask.SCENE] == 5
    assert harness.llm.max_in_flight == limit


async def test_render_progress_is_persisted_every_ten_points_and_always_when_terminal() -> None:
    harness = build_harness()

    await harness.run()

    progress = harness.store.events_of("render.progress")
    assert [event.payload["progress"] for event in progress] == [0, 5, 10, 24, 60, 100]
    assert [event.persist for event in progress] == [True, False, True, True, True, True]
    assert all(set(event.payload) == {"renderId", "stage", "progress"} for event in progress)
    assert [event.payload["renderId"] for event in progress] == [str(harness.renders.render_id)] * len(progress)


async def test_a_resumed_render_follows_the_recorded_render_instead_of_starting_another() -> None:
    harness = build_harness()
    harness.store.job = replace(harness.store.job, render_id=harness.renders.render_id)

    await harness.run()

    assert harness.renders.started == []
    assert harness.renders.followed == [harness.renders.render_id]


async def test_events_never_carry_prompts_skills_canaries_or_model_text_even_on_failure() -> None:
    harness = build_harness(script=FakeScript.for_task(LlmTask.GUARD, ["allow", "refuse-weapons"]))

    await harness.run()

    scanner = OutputScanner(list(harness.prompts.prompts.values()), harness.router.selected.all)
    serialized = json.dumps([[event.type, dict(event.payload)] for event in harness.store.events])
    assert not scanner.scan_text(serialized).blocked
    assert harness.store.failure is not None
    assert not scanner.scan_text(harness.store.failure[1]).blocked
    assert not any(prompt.canary in serialized for prompt in harness.prompts.prompts.values())


async def test_the_context_ready_event_lists_only_skill_slugs() -> None:
    harness = build_harness()

    await harness.run()

    (ready,) = harness.store.events_of("context.ready")
    assert ready.payload == {"skills": ["minimal-dark", "kinetic-typography", "flow-diagram", "cs-fundamentals"]}
    assert harness.router.calls[0][2] == PipelineConfig().skill_token_budget


async def test_the_planner_receives_every_selected_skill_as_a_system_block() -> None:
    harness = build_harness()

    await harness.run()

    (plan,) = harness.llm.calls_of(LlmTask.PLAN)
    assert len(plan.system_blocks) == 1 + len(harness.router.selected.all)
    for skill in harness.router.selected.all:
        assert any(skill.body in block for block in plan.system_blocks[1:])
    assert harness.prompts.prompts["planner.storyboard"].canary in plan.system_blocks[0]
