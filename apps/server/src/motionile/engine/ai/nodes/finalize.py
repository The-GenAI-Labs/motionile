from motionile.engine.ai.graphs.deps import PipelineDependencies
from motionile.engine.ai.graphs.errors import PipelineErrorCode, pipeline_error
from motionile.engine.ai.graphs.stages import Stage
from motionile.engine.ai.graphs.state import PipelineState
from motionile.engine.ai.nodes.common import job_id_of, stage_scope


async def run_finalize(deps: PipelineDependencies, state: PipelineState) -> PipelineState:
    job_id = job_id_of(state)
    async with stage_scope(deps, job_id, Stage.FINALIZE):
        narration = await deps.store.narration(job_id)
        if narration is None:
            raise pipeline_error(PipelineErrorCode.COMPOSITION_INVALID)
    await deps.store.complete(job_id, final_duration_ms=narration.total_duration_ms)
    return {}
