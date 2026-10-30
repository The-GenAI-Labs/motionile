from functools import partial
from typing import TYPE_CHECKING, Final

from evals.clients import FIXTURES_ROOT
from evals.context import SuiteContext, guarded
from evals.datasets import GoldenCase
from evals.errors import BrowserUnavailableError
from evals.modes import RunMode
from evals.results import CaseResult, Measurement, SuiteResult
from evals.scene_runs import run_scene_case
from evals.selection import SCENES_CHANGED, SCENES_FULL
from evals.sync.fixtures import FIXTURE_ASPECTS, fixture_composition
from evals.sync.probe import measure_offsets, within_tolerance

if TYPE_CHECKING:
    from motionile.engine.render.sandbox import RenderSandbox

NAME: Final = "sync"
FIXTURES_CASE: Final = "scene-fixtures"
SKIP_REASON: Final = "chromium_unavailable"
FIXTURES_MISSING: Final = "fixtures_unavailable"


def sync_scores(offsets: list[float]) -> dict[str, Measurement]:
    events = len(offsets)
    if not events:
        return {"sync_events_per_case": Measurement(0.0)}
    return {
        "sync_within_tolerance": Measurement(within_tolerance(offsets) / events, events),
        "sync_events_per_case": Measurement(float(events)),
    }


async def run_fixtures(sandbox: "RenderSandbox") -> CaseResult:
    html, narration = fixture_composition()
    offsets = await measure_offsets(sandbox, html, narration, list(FIXTURE_ASPECTS))
    return CaseResult(FIXTURES_CASE, sync_scores(offsets))


async def run_generated(context: SuiteContext, sandbox: "RenderSandbox", case: GoldenCase) -> CaseResult:
    artifacts = await run_scene_case(context, sandbox, case)
    offsets = await measure_offsets(sandbox, artifacts.html, artifacts.narration, list(artifacts.aspects))
    return CaseResult(case.id, sync_scores(offsets))


class SyncSuite:
    name = NAME

    async def run(self, context: SuiteContext) -> SuiteResult:
        cases = context.datasets.golden_cases(SCENES_CHANGED if context.changed else SCENES_FULL)
        versions = {"golden": context.datasets.golden.version}
        try:
            async with context.browser.sandbox() as sandbox:
                results = [await guarded(case.id, partial(run_generated, context, sandbox, case)) for case in cases]
                if (FIXTURES_ROOT / "scene").is_dir():
                    results.append(await guarded(FIXTURES_CASE, partial(run_fixtures, sandbox)))
                else:
                    results.append(CaseResult(FIXTURES_CASE, skipped=FIXTURES_MISSING))
        except BrowserUnavailableError:
            if context.mode is not RunMode.DETERMINISTIC or not context.allow_browser_skip:
                raise
            skipped = [CaseResult(case.id, skipped=SKIP_REASON) for case in cases]
            return SuiteResult(NAME, (*skipped, CaseResult(FIXTURES_CASE, skipped=SKIP_REASON)), versions)
        return SuiteResult(NAME, tuple(results), versions)


SUITE = SyncSuite()
