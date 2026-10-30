import importlib
import pkgutil
import time
from collections.abc import Sequence
from dataclasses import dataclass
from types import ModuleType

from evals.context import EvalSuite, SuiteContext
from evals.errors import EvalAbortError, UnknownSuiteError
from evals.results import SuiteResult
from evals.thresholds import SuiteVerdict, Thresholds, judge_suite

EVALS_PACKAGE = "evals"


@dataclass(frozen=True, slots=True)
class SuiteRun:
    result: SuiteResult
    verdict: SuiteVerdict | None
    duration_seconds: float

    @property
    def passed(self) -> bool:
        if self.result.fully_skipped:
            return True
        return self.result.errors == 0 and self.verdict is not None and self.verdict.passed


@dataclass(frozen=True, slots=True)
class Execution:
    runs: tuple[SuiteRun, ...]
    aborted: EvalAbortError | None = None

    @property
    def passed(self) -> bool:
        return self.aborted is None and all(run.passed for run in self.runs)


def discover_suites(package: ModuleType) -> list[EvalSuite]:
    suites: list[EvalSuite] = []
    for module_info in pkgutil.iter_modules(package.__path__):
        if not module_info.ispkg:
            continue
        module = importlib.import_module(f"{package.__name__}.{module_info.name}")
        suite: object = getattr(module, "SUITE", None)
        if isinstance(suite, EvalSuite):
            suites.append(suite)
    return sorted(suites, key=lambda candidate: candidate.name)


def select_suites(available: Sequence[EvalSuite], names: Sequence[str] | None) -> list[EvalSuite]:
    if names is None:
        return list(available)
    by_name = {suite.name: suite for suite in available}
    unknown = [name for name in names if name not in by_name]
    if unknown:
        raise UnknownSuiteError(f"unknown suites: {', '.join(unknown)}; available: {', '.join(sorted(by_name))}")
    return [by_name[name] for name in dict.fromkeys(names)]


async def run_suites(context: SuiteContext, suites: Sequence[EvalSuite], thresholds: Thresholds) -> Execution:
    runs: list[SuiteRun] = []
    for suite in suites:
        started = time.monotonic()
        try:
            result = await suite.run(context)
        except EvalAbortError as error:
            return Execution(tuple(runs), error)
        verdict = None if result.fully_skipped else judge_suite(result, thresholds, context.mode)
        runs.append(SuiteRun(result, verdict, time.monotonic() - started))
    return Execution(tuple(runs))
