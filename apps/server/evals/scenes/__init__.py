from functools import partial
from typing import TYPE_CHECKING, Final

from evals.context import SuiteContext, guarded
from evals.datasets import GoldenCase
from evals.errors import BrowserUnavailableError
from evals.modes import RunMode
from evals.results import CaseResult, SuiteResult
from evals.scene_runs import run_scene_case
from evals.scenes.metrics import scene_scores
from evals.selection import SCENES_CHANGED, SCENES_FULL

if TYPE_CHECKING:
    from motionile.engine.render.sandbox import RenderSandbox

NAME: Final = "scenes"
SKIP_REASON: Final = "chromium_unavailable"


async def run_case(context: SuiteContext, sandbox: "RenderSandbox", case: GoldenCase) -> CaseResult:
    artifacts = await run_scene_case(context, sandbox, case)
    return CaseResult(case.id, scene_scores(artifacts))


class ScenesSuite:
    name = NAME

    async def run(self, context: SuiteContext) -> SuiteResult:
        cases = context.datasets.golden_cases(SCENES_CHANGED if context.changed else SCENES_FULL)
        versions = {"golden": context.datasets.golden.version}
        try:
            async with context.browser.sandbox() as sandbox:
                results = [await guarded(case.id, partial(run_case, context, sandbox, case)) for case in cases]
        except BrowserUnavailableError:
            if context.mode is not RunMode.DETERMINISTIC or not context.allow_browser_skip:
                raise
            return SuiteResult(NAME, tuple(CaseResult(case.id, skipped=SKIP_REASON) for case in cases), versions)
        return SuiteResult(NAME, tuple(results), versions)


SUITE = ScenesSuite()
