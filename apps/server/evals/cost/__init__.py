from functools import partial
from typing import Final

from evals.context import SuiteContext, guarded
from evals.datasets import GoldenCase
from evals.errors import EvalError
from evals.harness import RigParts, StaticChecker, build_rig, make_job
from evals.results import CaseResult, Measurement, SuiteResult
from evals.selection import COST_CHANGED, COST_FULL
from evals.skill_library import LibrarySkillCatalog
from motionile.engine.ai.graphs.run import RunOutcome

NAME: Final = "cost"


class CostRunFailedError(EvalError):
    code = "eval_graph_failed"


async def run_case(context: SuiteContext, case: GoldenCase) -> CaseResult:
    async with context.sessions.open(NAME, case.id) as session:
        parts = RigParts(
            llm=session.llm,
            prompts=context.prompts,
            checker=StaticChecker(),
            embedder=session.embedder,
            limits=context.limits,
        )
        job = make_job(
            query=case.query, duration_seconds=case.duration_seconds, aspects=case.aspects, language=case.language
        )
        rig = await build_rig(job, parts, LibrarySkillCatalog(session.embedder))
        outcome = await rig.run()
        if outcome is not RunOutcome.FINISHED:
            raise CostRunFailedError(rig.store.failure[0] if rig.store.failure else outcome.value)
        scores = {
            "tokens_per_job": Measurement(float(session.ledger.tokens_for(job.id))),
            "cost_micros_per_job": Measurement(float(session.ledger.cost_for(job.id))),
            "calls_per_job": Measurement(float(len(session.ledger.calls_for(job.id)))),
        }
    return CaseResult(case.id, scores)


class CostSuite:
    name = NAME

    async def run(self, context: SuiteContext) -> SuiteResult:
        cases = context.datasets.golden_cases(COST_CHANGED if context.changed else COST_FULL)
        results = [await guarded(case.id, partial(run_case, context, case)) for case in cases]
        return SuiteResult(NAME, tuple(results), {"golden": context.datasets.golden.version})


SUITE = CostSuite()
