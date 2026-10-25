import json

from motionile.engine.ai.graphs.deps import PipelineDependencies
from motionile.engine.ai.graphs.errors import PipelineError, PipelineErrorCode, pipeline_error
from motionile.engine.ai.graphs.events import EventType, emit
from motionile.engine.ai.graphs.stages import Stage
from motionile.engine.ai.graphs.state import PipelineState
from motionile.engine.ai.llm.models import LlmCall, LlmTask
from motionile.engine.ai.llm.outputs import CritiqueIssue, StoryboardCritique
from motionile.engine.ai.nodes.blocks import query_block, storyboard_block, storyboard_issues_block
from motionile.engine.ai.nodes.calls import CRITIC_KEY, load_selected, system_blocks
from motionile.engine.ai.nodes.common import call_context, job_id_of, stage_scope
from motionile.engine.ai.nodes.plan import PlanContext
from motionile.engine.ai.ports import StoredStoryboard, StoryboardOrigin
from motionile.engine.ai.prompts.delimit import delimit


def critique_issues_block(issues: list[CritiqueIssue]) -> str:
    entries = [
        {
            "sceneId": issue.scene_id,
            "category": issue.category.value,
            "message": issue.message,
            "suggestedFix": issue.suggested_fix,
        }
        for issue in issues
    ]
    return delimit("issues", json.dumps(entries, ensure_ascii=False, separators=(",", ":")))


async def request_critique(plan: PlanContext, latest: StoredStoryboard) -> StoryboardCritique:
    blocks = [plan.context_block(), query_block(plan.job), storyboard_block(latest.content)]
    deterministic = plan.check(latest.content)
    if deterministic:
        blocks.append(storyboard_issues_block(deterministic))
    call = LlmCall(
        task=LlmTask.CRITIQUE,
        context=call_context(plan.job, Stage.CRITIQUE, "critique:review"),
        system_blocks=await system_blocks(plan.deps, CRITIC_KEY, plan.skills.all),
        user_blocks=blocks,
    )
    return (await plan.deps.llm.generate(call, StoryboardCritique)).output


async def revise_storyboard(
    plan: PlanContext, latest: StoredStoryboard, critique: StoryboardCritique
) -> StoredStoryboard | None:
    revised = await plan.request(
        key="critique:revision",
        previous=latest.content,
        issues_block=critique_issues_block(critique.blocking_issues),
    )
    if plan.check(revised):
        return None
    stored = await plan.deps.store.save_storyboard(plan.job.id, revised, StoryboardOrigin.CRITIC)
    payload = {"version": stored.version, "sceneCount": len(revised.scenes)}
    await emit(plan.deps, plan.job.id, EventType.STORYBOARD_READY, Stage.CRITIQUE, payload)
    return stored


async def ensure_output_allowed(plan: PlanContext, latest: StoredStoryboard) -> None:
    context = call_context(plan.job, Stage.CRITIQUE, "critique:output")
    verdict = await plan.deps.output_guard.check_storyboard(latest.content, context)
    if not verdict.allowed and verdict.code is not None and verdict.message is not None:
        raise PipelineError(verdict.code.value, verdict.message)


async def run_critique(deps: PipelineDependencies, state: PipelineState) -> PipelineState:
    job_id = job_id_of(state)
    async with stage_scope(deps, job_id, Stage.CRITIQUE):
        latest = await deps.store.latest_storyboard(job_id)
        if latest is None:
            raise pipeline_error(PipelineErrorCode.STORYBOARD_INVALID)
        job = await deps.store.snapshot(job_id)
        plan = PlanContext(deps, job, state, await load_selected(deps, state))
        revised = latest.version > state.get("planned_version", 0)
        blocking = 0
        if not revised:
            critique = await request_critique(plan, latest)
            blocking = len(critique.blocking_issues)
            replacement = await revise_storyboard(plan, latest, critique) if critique.blocking_issues else None
            revised = replacement is not None
            latest = replacement or latest
        payload = {"revised": revised, "blockingIssues": blocking}
        await emit(deps, job_id, EventType.CRITIQUE_COMPLETED, Stage.CRITIQUE, payload)
        await ensure_output_allowed(plan, latest)
    return {}
