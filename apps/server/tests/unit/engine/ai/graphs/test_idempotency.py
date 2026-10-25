from collections.abc import Sequence
from uuid import UUID

import pytest
from tests.fakes.pipeline import FakeRenderGateway, scene_issue
from tests.unit.engine.ai.graphs.support import SCENE_COUNT_FOR_THIRTY_SECONDS, Harness, build_harness

from motionile.engine.ai.graphs.deps import PipelineConfig
from motionile.engine.ai.graphs.issues import to_record
from motionile.engine.ai.graphs.run import RunOutcome
from motionile.engine.ai.graphs.state import PipelineState
from motionile.engine.ai.llm.models import LlmTask
from motionile.engine.ai.nodes.context import run_context
from motionile.engine.ai.nodes.guard import run_guard
from motionile.engine.ai.nodes.plan import run_plan
from motionile.engine.ai.nodes.repair import run_repair
from motionile.engine.ai.nodes.scenes import run_scenes
from motionile.engine.ai.nodes.voice import run_voice
from motionile.engine.ai.ports import JobSnapshot, NarrationScript, SceneAttemptKind


class FlakyRenders(FakeRenderGateway):
    def __init__(self) -> None:
        super().__init__()
        self.failures_left = 1

    async def start(self, job: JobSnapshot, html: str, scenes: Sequence[NarrationScript]) -> UUID:
        if self.failures_left:
            self.failures_left -= 1
            raise OSError("render service unreachable")
        return await super().start(job, html, scenes)


async def planned_state(harness: Harness) -> PipelineState:
    state = PipelineState(job_id=str(harness.job_id))
    for node in (run_guard, run_context, run_plan):
        state.update(await node(harness.deps, state))
    return state


async def test_running_a_finished_job_again_repeats_no_call() -> None:
    harness = build_harness()
    await harness.run()
    calls = dict(harness.tasks)
    events = len(harness.store.events)

    outcome = await harness.run()

    assert outcome is RunOutcome.FINISHED
    assert dict(harness.tasks) == calls
    assert len(harness.narrator.calls) == 1
    assert len(harness.renders.started) == 1
    assert len(harness.store.events) == events


async def test_a_crash_in_a_late_node_resumes_there_and_repeats_no_earlier_paid_call() -> None:
    clean = build_harness()
    await clean.run()
    harness = build_harness(renders=FlakyRenders())

    with pytest.raises(OSError, match="unreachable"):
        await harness.run()
    outcome = await harness.run()

    assert outcome is RunOutcome.FINISHED
    assert dict(harness.tasks) == dict(clean.tasks)
    assert len(harness.narrator.calls) == 1
    assert len(harness.checker.checked_html) == 1
    assert harness.store.stage_names.count("plan") == 1
    assert harness.store.stage_names.count("render") == 2


async def test_a_crash_in_the_middle_of_the_scenes_node_keeps_the_scenes_already_stored() -> None:
    harness = build_harness(
        config=PipelineConfig(scene_concurrency=1, render_poll_seconds=0.001),
        fail_call=(LlmTask.SCENE, 1, OSError("connection reset")),
    )

    with pytest.raises(OSError, match="connection reset"):
        await harness.run()
    stored_before = {saved.scene_id for saved in harness.store.saved_modules}
    outcome = await harness.run()

    assert outcome is RunOutcome.FINISHED
    scene_calls = [call.metadata["sceneId"] for call in harness.llm.calls_of(LlmTask.SCENE)]
    assert stored_before == {"hook"}
    assert scene_calls.count("hook") == 1
    assert set(harness.store.records) == set(scene_calls) == {"hook", "example", "recap"}


async def test_the_plan_node_skips_a_round_that_is_already_stored() -> None:
    harness = build_harness()
    state = await planned_state(harness)
    calls = len(harness.llm.calls_of(LlmTask.PLAN))

    again = await run_plan(harness.deps, state)

    assert again.get("planned_version") == state.get("planned_version")
    assert len(harness.llm.calls_of(LlmTask.PLAN)) == calls == 1
    assert len(harness.store.storyboards) == 1


async def test_the_voice_and_scenes_nodes_skip_what_is_already_stored() -> None:
    harness = build_harness()
    state = await planned_state(harness)
    await harness.store.approve_storyboard(harness.job_id, harness.store.storyboards[0].id)
    await run_voice(harness.deps, state)
    await run_voice(harness.deps, state)
    state.update(await run_scenes(harness.deps, state))
    await run_scenes(harness.deps, state)

    assert len(harness.narrator.calls) == 1
    assert harness.tasks[LlmTask.SCENE] == SCENE_COUNT_FOR_THIRTY_SECONDS
    assert len(harness.store.saved_modules) == SCENE_COUNT_FOR_THIRTY_SECONDS


async def test_the_repair_node_does_not_repair_again_a_scene_whose_repair_was_already_stored() -> None:
    harness = build_harness()
    state = await planned_state(harness)
    await harness.store.approve_storyboard(harness.job_id, harness.store.storyboards[0].id)
    await run_voice(harness.deps, state)
    state.update(await run_scenes(harness.deps, state))
    state["issues"] = [to_record(scene_issue("hook"), "hook")]

    first = await run_repair(harness.deps, state)
    assert harness.tasks[LlmTask.REPAIR] == 1
    assert harness.store.records["hook"].attempts == 1

    await run_repair(harness.deps, state)

    assert first.get("attempts", {}).get("hook") == 1
    assert harness.tasks[LlmTask.REPAIR] == 1
    assert [saved.kind for saved in harness.store.saved_modules if saved.scene_id == "hook"] == [
        SceneAttemptKind.INITIAL,
        SceneAttemptKind.REPAIR,
    ]
