from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from evals.errors import ThresholdsError
from evals.modes import RunMode
from evals.results import SuiteResult

THRESHOLDS_PATH: Final = Path(__file__).with_name("thresholds.yaml")

type BoundKind = Literal["min", "max"]


class Bound(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def bounds_are_coherent(self) -> Self:
        if self.min is None and self.max is None:
            raise ValueError("a bound needs min, max or both")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min cannot exceed max")
        return self


class MetricThreshold(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    default: Bound | None = None
    deterministic: Bound | None = None
    cassette: Bound | None = None
    live: Bound | None = None

    @model_validator(mode="after")
    def declares_a_bound(self) -> Self:
        if all(bound is None for bound in (self.default, self.deterministic, self.cassette, self.live)):
            raise ValueError("a metric needs at least one bound")
        return self

    def bound_for(self, mode: RunMode) -> Bound | None:
        specific = {
            RunMode.DETERMINISTIC: self.deterministic,
            RunMode.CASSETTE: self.cassette,
            RunMode.LIVE: self.live,
        }.get(mode)
        return specific or self.default


class ThresholdsFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suites: dict[str, dict[str, MetricThreshold]] = {}


type Thresholds = Mapping[str, Mapping[str, MetricThreshold]]


@dataclass(frozen=True, slots=True)
class ThresholdFailure:
    suite: str
    metric: str
    kind: BoundKind
    limit: float
    actual: float | None

    def describe(self) -> str:
        label = f"{self.suite}.{self.metric}"
        if self.actual is None:
            return f"{label}: not measured, {self.kind} {self.limit:.4f} required"
        relation = "below the required minimum" if self.kind == "min" else "above the allowed maximum"
        return f"{label}: {self.actual:.4f} is {relation} {self.limit:.4f}"


@dataclass(frozen=True, slots=True)
class SuiteVerdict:
    suite: str
    failures: tuple[ThresholdFailure, ...]
    gated: tuple[str, ...]
    ungated: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.failures


def load_thresholds(path: Path = THRESHOLDS_PATH) -> Thresholds:
    try:
        document: object = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return ThresholdsFile.model_validate(document).suites
    except (OSError, yaml.YAMLError) as error:
        raise ThresholdsError(f"{path.name}: the file cannot be read ({type(error).__name__})") from error
    except ValidationError as error:
        raise ThresholdsError(f"{path.name}: the document does not match the thresholds format") from error


def bound_failures(suite: str, metric: str, bound: Bound, actual: float | None) -> list[ThresholdFailure]:
    failures: list[ThresholdFailure] = []
    if bound.min is not None and (actual is None or actual < bound.min):
        failures.append(ThresholdFailure(suite, metric, "min", bound.min, actual))
    if bound.max is not None and (actual is None or actual > bound.max):
        failures.append(ThresholdFailure(suite, metric, "max", bound.max, actual))
    return failures


def judge_suite(result: SuiteResult, thresholds: Thresholds, mode: RunMode) -> SuiteVerdict:
    metrics = result.metrics
    declared = thresholds.get(result.suite, {})
    failures: list[ThresholdFailure] = []
    gated: list[str] = []
    ungated: list[str] = []
    for metric, threshold in declared.items():
        bound = threshold.bound_for(mode)
        if bound is None:
            ungated.append(metric)
            continue
        gated.append(metric)
        failures.extend(bound_failures(result.suite, metric, bound, metrics.get(metric)))
    return SuiteVerdict(result.suite, tuple(failures), tuple(gated), tuple(ungated))


def judge_suites(results: Sequence[SuiteResult], thresholds: Thresholds, mode: RunMode) -> list[SuiteVerdict]:
    return [judge_suite(result, thresholds, mode) for result in results if not result.fully_skipped]


def applied_bounds(thresholds: Thresholds, suite: str, mode: RunMode) -> dict[str, dict[str, float]]:
    applied: dict[str, dict[str, float]] = {}
    for metric, threshold in thresholds.get(suite, {}).items():
        bound = threshold.bound_for(mode)
        if bound is None:
            continue
        applied[metric] = {kind: limit for kind, limit in (("min", bound.min), ("max", bound.max)) if limit is not None}
    return applied
