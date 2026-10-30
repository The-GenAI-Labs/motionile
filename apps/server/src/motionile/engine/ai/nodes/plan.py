from dataclasses import dataclass

from motionile.engine.ai.graphs.deps import PipelineDependencies
from motionile.engine.ai.graphs.errors import PipelineErrorCode, pipeline_error
from motionile.engine.ai.graphs.events import EventType, emit
from motionile.engine.ai.graphs.stages import Stage
from motionile.engine.ai.graphs.state import PipelineState
from motionile.engine.ai.llm.models import LlmCall, LlmTask
from motionile.engine.ai.nodes.blocks import (
    instructions_block,
    plan_context,
    query_block,
    storyboard_block,
    storyboard_issues_block,
)
from motionile.engine.ai.nodes.calls import PLANNER_KEY, load_selected, plan_metadata, system_blocks
from motionile.engine.ai.nodes.common import call_context, job_id_of, stage_scope
from motionile.engine.ai.ports import JobSnapshot, SelectedSkills, StoryboardOrigin
from motionile.engine.ai.storyboard import Storyboard, StoryboardExpectation, StoryboardIssue, validate_storyboard

MAX_PLAN_ASKS = 2


@dataclass(frozen=True, slots=True)
class PlanContext:
    deps: PipelineDependencies
    job: JobSnapshot
    state: PipelineState
    skills: SelectedSkills

    @property
    def expectation(self) -> StoryboardExpectation:
        options = self.job.options
        return StoryboardExpectation(
            duration_ms=options.target_duration_ms,
            aspects=options.aspects,
            language=options.language,
            style=options.style,
        )

    @property
    def scenes_to_change(self) -> list[str]:
        revision = self.job.options.revision
        return list(revision.scene_ids) if revision is not None else []

    @property
    def instructions(self) -> str | None:
        regenerated = self.state.get("instructions")
        if regenerated:
            return regenerated
        revision = self.job.options.revision
        return revision.instructions if revision is not None else None

    def check(self, storyboard: Storyboard) -> list[StoryboardIssue]:
        return validate_storyboard(storyboard, self.expectation, self.deps.config.limits)

    def context_block(self) -> str:
        return plan_context(
            self.job,
            [skill.summary.slug for skill in self.skills.visual],
            self.state.get("context_text", ""),
            self.deps.config.limits,
            self.scenes_to_change,
        )

    async def request(self, *, key: str, previous: Storyboard | None, issues_block: str | None) -> Storyboard:
        blocks = [self.context_block(), query_block(self.job)]
        if self.instructions:
            blocks.append(instructions_block(self.instructions))
        if previous is not None:
            blocks.append(storyboard_block(previous))
        if issues_block is not None:
            blocks.append(issues_block)
        call = LlmCall(
            task=LlmTask.PLAN,
            context=call_context(self.job, Stage.PLAN, key),
            system_blocks=await system_blocks(self.deps, PLANNER_KEY, self.skills.all),
            user_blocks=blocks,
            metadata=plan_metadata(self.job),
        )
        return (await self.deps.llm.generate(call, Storyboard)).output


async def plan_valid_storyboard(plan: PlanContext, previous: Storyboard | None) -> Storyboard:
    base = plan.state.get("base_version", 0)
    candidate = previous
    issues_block: str | None = None
    codes: set[str] = set()
    for attempt in range(MAX_PLAN_ASKS):
        candidate = await plan.request(key=f"plan:{base}:{attempt}", previous=candidate, issues_block=issues_block)
        issues = plan.check(candidate)
        if not issues:
            return candidate
        issues_block = storyboard_issues_block(issues)
        codes = {issue.code.value for issue in issues}
    raise pipeline_error(PipelineErrorCode.STORYBOARD_INVALID, ", ".join(sorted(codes)))


async def run_plan(deps: PipelineDependencies, state: PipelineState) -> PipelineState:
    job_id = job_id_of(state)
    async with stage_scope(deps, job_id, Stage.PLAN):
        latest = await deps.store.latest_storyboard(job_id)
        if latest is not None and latest.version > state.get("base_version", 0):
            return {"planned_version": latest.version, "instructions": None}
        job = await deps.store.snapshot(job_id)
        plan = PlanContext(deps, job, state, await load_selected(deps, state))
        previous = latest.content if latest is not None else (job.parent.storyboard if job.parent else None)
        storyboard = await plan_valid_storyboard(plan, previous)
        origin = StoryboardOrigin.PLANNER if latest is None else StoryboardOrigin.REGENERATION
        stored = await deps.store.save_storyboard(job_id, storyboard, origin)
        payload = {"version": stored.version, "sceneCount": len(storyboard.scenes)}
        await emit(deps, job_id, EventType.STORYBOARD_READY, Stage.PLAN, payload)
        return {"planned_version": stored.version, "instructions": None}
