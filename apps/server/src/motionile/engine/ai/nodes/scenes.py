from functools import partial

from motionile.engine.ai.graphs.deps import PipelineDependencies
from motionile.engine.ai.graphs.events import EventType, FallbackReason, emit
from motionile.engine.ai.graphs.issues import module_issues, static_records
from motionile.engine.ai.graphs.stages import Stage
from motionile.engine.ai.graphs.state import PipelineState
from motionile.engine.ai.llm.models import ModelOutputInvalidError
from motionile.engine.ai.nodes.common import ensure_active, job_id_of, run_bounded, stage_scope
from motionile.engine.ai.nodes.scene_work import SceneWork, load_scene_work, produce_module, store_fallback
from motionile.engine.ai.ports import SceneAttemptKind
from motionile.engine.ai.storyboard import StoryboardScene


async def build_scene(work: SceneWork, scene: StoryboardScene) -> None:
    await ensure_active(work.deps, work.job.id)
    try:
        module = await produce_module(work, scene)
    except ModelOutputInvalidError:
        await store_fallback(work, scene.id, FallbackReason.MODEL_OUTPUT_INVALID, Stage.SCENES)
        return
    await work.deps.store.save_scene_module(work.job.id, module, SceneAttemptKind.INITIAL, module_issues(module))
    await emit(work.deps, work.job.id, EventType.SCENE_GENERATED, Stage.SCENES, {"sceneId": scene.id})


async def run_scenes(deps: PipelineDependencies, state: PipelineState) -> PipelineState:
    job_id = job_id_of(state)
    async with stage_scope(deps, job_id, Stage.SCENES):
        work = await load_scene_work(deps, state, job_id)
        stored = {record.scene_id for record in await deps.store.scenes(job_id) if record.module is not None}
        pending = [scene for scene in work.storyboard.scenes if scene.id not in stored]
        await run_bounded(deps.config.scene_concurrency, [partial(build_scene, work, scene) for scene in pending])
        records = await deps.store.scenes(job_id)
        return {
            "issues": static_records(records),
            "attempts": {record.scene_id: record.attempts for record in records},
        }
