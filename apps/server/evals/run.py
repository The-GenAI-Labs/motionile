import importlib
import pkgutil
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Protocol, runtime_checkable

import yaml
from pydantic import BaseModel, ConfigDict

EVALS_PACKAGE = "evals"
THRESHOLDS_PATH = Path(__file__).with_name("thresholds.yaml")

type Metrics = Mapping[str, float]
type Thresholds = Mapping[str, Mapping[str, float]]


@runtime_checkable
class EvalSuite(Protocol):
    @property
    def name(self) -> str: ...

    def run(self) -> Metrics: ...


class ThresholdsFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suites: dict[str, dict[str, float]] = {}


@dataclass(frozen=True)
class ThresholdFailure:
    suite: str
    metric: str
    minimum: float
    actual: float | None

    def describe(self) -> str:
        observed = "missing" if self.actual is None else f"{self.actual:.4f}"
        return f"{self.suite}.{self.metric}: {observed} is below the required {self.minimum:.4f}"


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


def load_thresholds(path: Path) -> Thresholds:
    document: object = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ThresholdsFile.model_validate(document).suites


def evaluate(suites: Iterable[EvalSuite], thresholds: Thresholds) -> list[ThresholdFailure]:
    failures: list[ThresholdFailure] = []
    for suite in suites:
        metrics = suite.run()
        for metric, minimum in thresholds.get(suite.name, {}).items():
            actual = metrics.get(metric)
            if actual is None or actual < minimum:
                failures.append(ThresholdFailure(suite.name, metric, minimum, actual))
    return failures


def main() -> int:
    suites = discover_suites(importlib.import_module(EVALS_PACKAGE))
    if not suites:
        sys.stdout.write("No eval suites are registered yet.\n")
        return 0
    failures = evaluate(suites, load_thresholds(THRESHOLDS_PATH))
    for failure in failures:
        sys.stdout.write(f"FAIL {failure.describe()}\n")
    sys.stdout.write(f"{len(suites)} suites evaluated, {len(failures)} threshold failures.\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
