from datetime import timedelta

from langgraph.types import interrupt

from motionile.engine.ai.graphs.deps import PipelineDependencies
from motionile.engine.ai.graphs.errors import PipelineError, PipelineErrorCode, pipeline_error
from motionile.engine.ai.graphs.events import EventType, emit
from motionile.engine.ai.graphs.resume import ApprovalKind, ApprovalResume
from motionile.engine.ai.graphs.stages import Stage
from motionile.engine.ai.graphs.state import PipelineState
from motionile.engine.ai.job_options import JobStatus
from motionile.engine.ai.nodes.common import call_context, ensure_active, job_id_of, stage_scope
from motionile.engine.ai.nodes.guard import ensure_input_allowed
from motionile.engine.ai.ports import StoredStoryboard


async def latest_or_fail(deps: PipelineDependencies, state: PipelineState) -> StoredStoryboard:
    latest = await deps.store.latest_storyboard(job_id_of(state))
    if latest is None:
        raise pipeline_error(PipelineErrorCode.STORYBOARD_INVALID)
    return latest


async def run_approval(deps: PipelineDependencies, state: PipelineState) -> PipelineState:
    job_id = job_id_of(state)
    job = await deps.store.snapshot(job_id)
    review = job.options.review_storyboard
    status = JobStatus.AWAITING_APPROVAL if review else JobStatus.PLANNING
    async with stage_scope(deps, job_id, Stage.APPROVAL, status=status):
        latest = await latest_or_fail(deps, state)
        if not review:
            await deps.store.approve_storyboard(job_id, latest.id)
            return {"approval_requested": False}
        expires_at = deps.clock.now() + timedelta(hours=deps.config.approval_timeout_hours)
        payload = {"version": latest.version, "expiresAt": expires_at.isoformat()}
        await emit(deps, job_id, EventType.APPROVAL_REQUESTED, Stage.APPROVAL, payload)
        return {"approval_requested": True, "approval_version": latest.version}


async def approve(deps: PipelineDependencies, state: PipelineState) -> PipelineState:
    job_id = job_id_of(state)
    latest = await latest_or_fail(deps, state)
    if latest.version != state.get("approval_version"):
        job = await deps.store.snapshot(job_id)
        verdict = await deps.output_guard.check_storyboard(
            latest.content, call_context(job, Stage.DECISION, f"decision:output:{latest.version}")
        )
        if not verdict.allowed and verdict.code is not None and verdict.message is not None:
            raise PipelineError(verdict.code.value, verdict.message)
    await deps.store.approve_storyboard(job_id, latest.id)
    await emit(deps, job_id, EventType.APPROVAL_GRANTED, Stage.DECISION, {"version": latest.version})
    return {"decision": "approve", "approval_requested": False}


async def regenerate(deps: PipelineDependencies, state: PipelineState, resume: ApprovalResume) -> PipelineState:
    job = await deps.store.snapshot(job_id_of(state))
    latest = await latest_or_fail(deps, state)
    if resume.instructions is not None:
        await ensure_input_allowed(
            deps, job, resume.instructions, "instructions", f"decision:instructions:{latest.version}"
        )
    return {
        "decision": "regenerate",
        "instructions": resume.instructions,
        "base_version": latest.version,
        "approval_requested": False,
    }


async def run_decision(deps: PipelineDependencies, state: PipelineState) -> PipelineState:
    resume = ApprovalResume.model_validate(interrupt({"version": state.get("approval_version", 0)}))
    await ensure_active(deps, job_id_of(state))
    if resume.kind is ApprovalKind.APPROVE:
        return await approve(deps, state)
    return await regenerate(deps, state, resume)
