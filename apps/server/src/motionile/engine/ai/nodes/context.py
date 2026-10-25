from motionile.engine.ai.context import builtin_providers, gather_sections, render_sections
from motionile.engine.ai.graphs.deps import PipelineDependencies
from motionile.engine.ai.graphs.errors import PipelineErrorCode, pipeline_error
from motionile.engine.ai.graphs.events import EventType, emit
from motionile.engine.ai.graphs.stages import Stage
from motionile.engine.ai.graphs.state import PipelineState
from motionile.engine.ai.nodes.common import call_context, job_id_of, stage_scope
from motionile.engine.ai.scenes.style_tokens import style_tokens_for
from motionile.engine.ai.skills.errors import NoStyleSkillError


async def run_context(deps: PipelineDependencies, state: PipelineState) -> PipelineState:
    job_id = job_id_of(state)
    async with stage_scope(deps, job_id, Stage.CONTEXT):
        job = await deps.store.snapshot(job_id)
        try:
            selected = await deps.skill_router.select(
                job, call_context(job, Stage.CONTEXT, "context:route"), token_budget=deps.config.skill_token_budget
            )
        except NoStyleSkillError:
            raise pipeline_error(PipelineErrorCode.NO_STYLE_SKILL) from None
        style = selected.style.summary.slug
        if style != job.options.style or style_tokens_for(style) is None:
            raise pipeline_error(PipelineErrorCode.NO_STYLE_SKILL)
        sections = await gather_sections((*builtin_providers(), *deps.providers), job)
        slugs = [skill.summary.slug for skill in selected.all]
        await emit(deps, job_id, EventType.CONTEXT_READY, Stage.CONTEXT, {"skills": list(slugs)})
        return {"skills": slugs, "context_text": render_sections(sections)}
