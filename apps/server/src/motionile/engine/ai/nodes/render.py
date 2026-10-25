import asyncio
from uuid import UUID

from motionile.engine.ai.graphs.deps import PipelineDependencies
from motionile.engine.ai.graphs.errors import JobCancelled, JobEnded, PipelineErrorCode, pipeline_error
from motionile.engine.ai.graphs.events import emit_progress
from motionile.engine.ai.graphs.stages import Stage
from motionile.engine.ai.graphs.state import PipelineState
from motionile.engine.ai.nodes.common import ensure_active, job_id_of, stage_scope
from motionile.engine.ai.nodes.composition import Composition, load_composition
from motionile.engine.ai.ports import JobSnapshot, NarrationScript, RenderProgress

PERSIST_EVERY_POINTS = 10


def scripts_of(composition: Composition) -> list[NarrationScript]:
    return [NarrationScript(scene_id=scene.id, text=scene.narration) for scene in composition.storyboard.scenes]


async def ensure_render(deps: PipelineDependencies, job: JobSnapshot, composition: Composition) -> UUID:
    if job.render_id is not None:
        return job.render_id
    render_id = await deps.renders.start(job, composition.html, scripts_of(composition))
    await deps.store.attach_render(job.id, render_id)
    return render_id


async def publish(deps: PipelineDependencies, job_id: UUID, progress: RenderProgress, last_persisted: int) -> int:
    bucket = progress.progress // PERSIST_EVERY_POINTS
    persist = progress.terminal or bucket > last_persisted
    payload = {"renderId": str(progress.render_id), "stage": progress.stage, "progress": progress.progress}
    await emit_progress(deps, job_id, payload, persist=persist)
    return max(bucket, last_persisted) if persist else last_persisted


async def follow_to_end(deps: PipelineDependencies, job_id: UUID, render_id: UUID) -> RenderProgress:
    last_persisted = -1
    while True:
        async for progress in deps.renders.follow(render_id):
            await ensure_active(deps, job_id)
            last_persisted = await publish(deps, job_id, progress, last_persisted)
            if progress.terminal:
                return progress
        await asyncio.sleep(deps.config.render_poll_seconds)


async def await_render(deps: PipelineDependencies, job_id: UUID, render_id: UUID) -> RenderProgress:
    try:
        async with asyncio.timeout(deps.config.render_timeout_seconds):
            return await follow_to_end(deps, job_id, render_id)
    except (JobCancelled, JobEnded):
        await deps.renders.cancel(render_id)
        raise
    except TimeoutError:
        await deps.renders.cancel(render_id)
        raise pipeline_error(PipelineErrorCode.RENDER_FAILED, "timed out") from None


async def run_render(deps: PipelineDependencies, state: PipelineState) -> PipelineState:
    job_id = job_id_of(state)
    async with stage_scope(deps, job_id, Stage.RENDER):
        job = await deps.store.snapshot(job_id)
        composition = await load_composition(deps, job_id)
        render_id = await ensure_render(deps, job, composition)
        final = await await_render(deps, job_id, render_id)
        await ensure_active(deps, job_id)
        if final.failed:
            raise pipeline_error(PipelineErrorCode.RENDER_FAILED, final.error_code or "unknown")
    return {}
