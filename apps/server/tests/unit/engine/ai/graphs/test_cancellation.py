import pytest
from tests.fakes.pipeline import FakeRenderGateway, broken_on_checks
from tests.unit.engine.ai.graphs.support import build_harness
from tests.unit.engine.ai.graphs.test_happy_path import EXPECTED_STAGES

from motionile.engine.ai.graphs.deps import PipelineConfig
from motionile.engine.ai.graphs.run import RunOutcome
from motionile.engine.ai.job_options import JobStatus
from motionile.engine.ai.llm.models import LlmTask


@pytest.mark.parametrize("stage", EXPECTED_STAGES)
async def test_cancelling_before_a_node_ends_the_job_cancelled_and_no_later_node_runs(stage: str) -> None:
    harness = build_harness()
    harness.store.cancel_before.add(stage)

    outcome = await harness.run()

    assert outcome is RunOutcome.CANCELLED
    assert harness.store.job.status is JobStatus.CANCELLED
    assert harness.store.stage_names == EXPECTED_STAGES[: EXPECTED_STAGES.index(stage)]
    assert harness.store.event_types[-1] == "job.cancelled"
    assert harness.store.failure is None
    assert harness.store.completed_duration_ms is None


async def test_cancelling_before_the_repair_node_stops_before_any_repair_call() -> None:
    harness = build_harness(rules=[broken_on_checks("example", {0})])
    harness.store.cancel_before.add("repair")

    outcome = await harness.run()

    assert outcome is RunOutcome.CANCELLED
    assert "repair" not in harness.store.stage_names
    assert "render" not in harness.store.stage_names
    assert harness.tasks[LlmTask.REPAIR] == 0


async def test_cancelling_during_scene_generation_stops_the_remaining_scenes() -> None:
    harness = build_harness(
        config=PipelineConfig(scene_concurrency=1, render_poll_seconds=0.001),
        before_call=lambda call: harness.store.request_cancel() if call.task is LlmTask.SCENE else None,
    )

    outcome = await harness.run()

    assert outcome is RunOutcome.CANCELLED
    assert harness.tasks[LlmTask.SCENE] == 1
    assert len(harness.store.saved_modules) == 1
    assert harness.renders.started == []
    assert "compose" not in harness.store.stage_names


async def test_cancelling_during_the_render_cancels_the_active_render() -> None:
    renders = FakeRenderGateway(on_progress=lambda index: harness.store.request_cancel() if index == 2 else None)
    harness = build_harness(renders=renders)

    outcome = await harness.run()

    assert outcome is RunOutcome.CANCELLED
    assert renders.cancelled == [renders.render_id]
    assert harness.store.job.status is JobStatus.CANCELLED
    assert harness.store.completed_duration_ms is None
    assert "finalize" not in harness.store.stage_names


async def test_a_job_that_already_ended_is_left_alone() -> None:
    harness = build_harness()
    await harness.store.fail(harness.job_id, "llm_unavailable", "gone")

    outcome = await harness.run()

    assert outcome is RunOutcome.FAILED
    assert harness.tasks == {}
    assert harness.store.failure == ("llm_unavailable", "gone")
