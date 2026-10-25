from collections.abc import Mapping, Sequence
from functools import partial

from motionile.engine.ai.graphs.deps import PipelineDependencies
from motionile.engine.ai.graphs.events import EventType, FallbackReason, emit
from motionile.engine.ai.graphs.issues import group_records, issue_codes, static_records
from motionile.engine.ai.graphs.stages import Stage
from motionile.engine.ai.graphs.state import PipelineState
from motionile.engine.ai.llm.models import LlmTask, ModelOutputInvalidError
from motionile.engine.ai.nodes.common import ensure_active, job_id_of, run_bounded, stage_scope
from motionile.engine.ai.nodes.scene_work import SceneWork, ask_module, load_scene_work, store_fallback
from motionile.engine.ai.ports import CompositionIssue, SceneAttemptKind, SceneRecord


async def repair_scene(
    work: SceneWork, record: SceneRecord, issues: Sequence[CompositionIssue], accounted_attempts: int
) -> None:
    if record.is_fallback or record.module is None or record.attempts > accounted_attempts:
        return
    await ensure_active(work.deps, work.job.id)
    if record.attempts >= work.deps.config.max_repairs:
        await store_fallback(work, record.scene_id, FallbackReason.REPAIRS_EXHAUSTED, Stage.REPAIR)
        return
    attempt = record.attempts + 1
    try:
        module = await ask_module(
            work,
            work.scene(record.scene_id),
            stage=Stage.REPAIR,
            task=LlmTask.REPAIR,
            key=f"repair:{record.scene_id}:{attempt}",
            attempt=attempt,
            previous=record.module,
            issues=issues,
        )
    except ModelOutputInvalidError:
        await store_fallback(work, record.scene_id, FallbackReason.MODEL_OUTPUT_INVALID, Stage.REPAIR)
        return
    await work.deps.store.save_scene_module(work.job.id, module, SceneAttemptKind.REPAIR, issues)
    payload = {"sceneId": record.scene_id, "attempt": attempt, "issueCodes": issue_codes(issues)}
    await emit(work.deps, work.job.id, EventType.SCENE_REPAIRED, Stage.REPAIR, payload)


def reviewed_after(state: PipelineState, repaired: Mapping[str, object]) -> list[str]:
    return [scene_id for scene_id in state.get("reviewed", []) if scene_id not in repaired]


async def run_repair(deps: PipelineDependencies, state: PipelineState) -> PipelineState:
    job_id = job_id_of(state)
    async with stage_scope(deps, job_id, Stage.REPAIR):
        work = await load_scene_work(deps, state, job_id)
        failing = group_records(state.get("issues", []))
        accounted = state.get("attempts", {})
        records = {record.scene_id: record for record in await deps.store.scenes(job_id)}
        jobs = [
            partial(repair_scene, work, records[scene_id], issues, accounted.get(scene_id, 0))
            for scene_id, issues in failing.items()
            if scene_id in records
        ]
        await run_bounded(deps.config.scene_concurrency, jobs)
        refreshed = await deps.store.scenes(job_id)
        return {
            "issues": static_records(refreshed),
            "attempts": {record.scene_id: record.attempts for record in refreshed},
            "reviewed": reviewed_after(state, failing),
        }
