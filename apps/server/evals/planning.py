from dataclasses import dataclass

from evals.clients import CaseSession
from evals.context import SuiteContext
from evals.harness import Rig, RigParts, StaticChecker, build_rig
from evals.skill_library import LibrarySkillCatalog
from motionile.engine.ai.graphs.errors import PipelineError
from motionile.engine.ai.llm.models import LlmError
from motionile.engine.ai.nodes.context import run_context
from motionile.engine.ai.nodes.critique import run_critique
from motionile.engine.ai.nodes.guard import run_guard
from motionile.engine.ai.nodes.plan import run_plan
from motionile.engine.ai.ports import JobSnapshot
from motionile.engine.ai.storyboard import Storyboard


@dataclass(frozen=True, slots=True)
class PlanOutcome:
    rig: Rig
    storyboard: Storyboard | None
    error: str | None


async def rig_for(context: SuiteContext, session: CaseSession, job: JobSnapshot) -> Rig:
    parts = RigParts(
        llm=session.llm,
        prompts=context.prompts,
        checker=StaticChecker(),
        embedder=session.embedder,
        limits=context.limits,
    )
    return await build_rig(job, parts, LibrarySkillCatalog(session.embedder))


async def plan_job(context: SuiteContext, session: CaseSession, job: JobSnapshot, *, guarded: bool) -> PlanOutcome:
    rig = await rig_for(context, session, job)
    nodes = [run_guard, run_context, run_plan, run_critique] if guarded else [run_context, run_plan, run_critique]
    try:
        await rig.run_nodes(nodes)
    except PipelineError as error:
        return PlanOutcome(rig, None, error.code)
    except LlmError as error:
        return PlanOutcome(rig, None, error.code.value)
    latest = rig.store.storyboards[-1].content if rig.store.storyboards else None
    return PlanOutcome(rig, latest, None)
