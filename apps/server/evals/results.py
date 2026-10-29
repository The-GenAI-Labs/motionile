from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final

FLOAT_DIGITS: Final = 6


@dataclass(frozen=True, slots=True)
class Measurement:
    value: float
    weight: float = 1.0


type CaseScores = Mapping[str, Measurement]


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    scores: CaseScores = field(default_factory=dict[str, Measurement])
    error: str | None = None
    skipped: str | None = None

    @property
    def measured(self) -> bool:
        return self.error is None and self.skipped is None


def aggregate_metrics(cases: Iterable[CaseResult]) -> dict[str, float]:
    totals: dict[str, float] = {}
    weights: dict[str, float] = {}
    for case in cases:
        if not case.measured:
            continue
        for name, measurement in case.scores.items():
            totals[name] = totals.get(name, 0.0) + measurement.value * measurement.weight
            weights[name] = weights.get(name, 0.0) + measurement.weight
    return {name: round(totals[name] / weights[name], FLOAT_DIGITS) for name in sorted(totals) if weights[name] > 0}


@dataclass(frozen=True, slots=True)
class SuiteResult:
    suite: str
    cases: tuple[CaseResult, ...]
    dataset_versions: Mapping[str, str]

    @property
    def metrics(self) -> dict[str, float]:
        return aggregate_metrics(self.cases)

    @property
    def dataset_label(self) -> str:
        return "_".join(sorted(set(self.dataset_versions.values())))

    @property
    def errors(self) -> int:
        return sum(1 for case in self.cases if case.error is not None)

    @property
    def skipped(self) -> int:
        return sum(1 for case in self.cases if case.skipped is not None)

    @property
    def measured(self) -> int:
        return sum(1 for case in self.cases if case.measured)

    @property
    def fully_skipped(self) -> bool:
        return bool(self.cases) and self.skipped == len(self.cases)


def rate(flags: Iterable[bool]) -> float:
    items = list(flags)
    return sum(1 for flag in items if flag) / len(items) if items else 0.0


def ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0
