from motionile.engine.ai.graphs.deps import PipelineDependencies
from motionile.engine.ai.graphs.errors import PipelineError
from motionile.engine.ai.graphs.events import EventType, emit
from motionile.engine.ai.graphs.stages import Stage
from motionile.engine.ai.graphs.state import PipelineState
from motionile.engine.ai.guardrails.rules import InputKind
from motionile.engine.ai.nodes.common import call_context, job_id_of, stage_scope
from motionile.engine.ai.ports import JobSnapshot


async def ensure_input_allowed(
    deps: PipelineDependencies, job: JobSnapshot, text: str, kind: InputKind, key: str
) -> None:
    result = await deps.input_guard.check(text, call_context(job, Stage.GUARD, key), kind)
    if not result.allowed and result.code is not None and result.message is not None:
        raise PipelineError(result.code.value, result.message)


async def run_guard(deps: PipelineDependencies, state: PipelineState) -> PipelineState:
    job_id = job_id_of(state)
    async with stage_scope(deps, job_id, Stage.GUARD):
        job = await deps.store.snapshot(job_id)
        text = job.query or (job.topic.title if job.topic is not None else "")
        await ensure_input_allowed(deps, job, text, "query", "guard:query")
        revision = job.options.revision
        if revision is not None:
            await ensure_input_allowed(deps, job, revision.instructions, "instructions", "guard:revision")
        await emit(deps, job_id, EventType.GUARD_PASSED, Stage.GUARD)
    return {}
