from functools import partial
from typing import Final

from evals.context import SuiteContext, guarded
from evals.datasets import DurationCase, GoldenCase
from evals.harness import make_job
from evals.planner.metrics import concept_coverage, judged_scores, structure_scores
from evals.planning import plan_job
from evals.results import CaseResult, Measurement, SuiteResult
from evals.selection import PLANNER_DURATION_CHANGED, PLANNER_GOLDEN_CHANGED

NAME: Final = "planner"


async def run_golden(context: SuiteContext, case: GoldenCase) -> CaseResult:
    async with context.sessions.open(NAME, case.id) as session:
        job = make_job(
            query=case.query, duration_seconds=case.duration_seconds, aspects=case.aspects, language=case.language
        )
        outcome = await plan_job(context, session, job, guarded=True)
        scores = structure_scores(outcome.storyboard, case.duration_ms, case.duration_seconds, context.limits)
        if outcome.storyboard is None:
            scores["concept_coverage"] = Measurement(0.0)
            if session.judge is not None:
                scores.update({"factual_accuracy": Measurement(1.0), "pedagogy": Measurement(1.0)})
            return CaseResult(case.id, scores)
        confirmed = None
        if session.judge is not None:
            verdict = await session.judge.content(case, outcome.storyboard)
            confirmed = verdict.covered_concepts
            scores.update(judged_scores(verdict))
        scores["concept_coverage"] = Measurement(concept_coverage(case, outcome.storyboard, confirmed))
        return CaseResult(case.id, scores)


async def run_duration(context: SuiteContext, case: DurationCase) -> CaseResult:
    async with context.sessions.open(NAME, case.id) as session:
        job = make_job(query=case.query, duration_seconds=case.duration_seconds, aspects=case.aspects)
        outcome = await plan_job(context, session, job, guarded=True)
        scores = structure_scores(outcome.storyboard, case.duration_ms, case.duration_seconds, context.limits)
        return CaseResult(case.id, scores)


class PlannerSuite:
    name = NAME

    async def run(self, context: SuiteContext) -> SuiteResult:
        golden_ids = PLANNER_GOLDEN_CHANGED if context.changed else None
        duration_ids = PLANNER_DURATION_CHANGED if context.changed else None
        results: list[CaseResult] = []
        for golden in context.datasets.golden_cases(golden_ids):
            results.append(await guarded(golden.id, partial(run_golden, context, golden)))
        for duration in context.datasets.duration_cases(duration_ids):
            results.append(await guarded(duration.id, partial(run_duration, context, duration)))
        versions = {"golden": context.datasets.golden.version, "duration": context.datasets.duration.version}
        return SuiteResult(NAME, tuple(results), versions)


SUITE = PlannerSuite()
