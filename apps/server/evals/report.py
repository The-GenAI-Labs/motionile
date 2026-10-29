from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, JsonValue
from pydantic.alias_generators import to_camel

from evals.modes import RunMode, Selection
from evals.results import CaseResult, SuiteResult
from evals.thresholds import SuiteVerdict, ThresholdFailure, Thresholds, applied_bounds
from motionile.engine.ai.llm.models import LlmTask, RoutingConfig

REPORT_VERSION: Final = 1

type SuiteStatus = Literal["passed", "failed", "skipped", "errored"]


class ReportModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True, serialize_by_alias=True, frozen=True)


class CaseReport(ReportModel):
    id: str
    scores: dict[str, float] = {}
    weights: dict[str, float] = {}
    error: str | None = None
    skipped: str | None = None


class SuiteReport(ReportModel):
    name: str
    status: SuiteStatus
    metrics: dict[str, float]
    thresholds: dict[str, dict[str, float]]
    ungated_metrics: list[str]
    failures: list[str]
    dataset_versions: dict[str, str]
    cases: list[CaseReport]
    measured_cases: int
    skipped_cases: int
    errored_cases: int
    duration_seconds: float


class ModelRoute(ReportModel):
    primary: str
    fallbacks: list[str]


class RunReport(ReportModel):
    version: int = REPORT_VERSION
    mode: RunMode
    requested_mode: RunMode
    selection: Selection
    trigger: str | None
    recorded: bool
    prompt_source: str
    prompt_version_ids: list[str]
    started_at: datetime
    finished_at: datetime
    passed: bool
    error_code: str | None
    live_spend_micros_usd: int
    budget_micros_usd: int | None
    model_configuration: dict[str, ModelRoute]
    suites: list[SuiteReport]


def case_report(case: CaseResult) -> CaseReport:
    return CaseReport(
        id=case.case_id,
        scores={name: round(measurement.value, 6) for name, measurement in case.scores.items()},
        weights={name: measurement.weight for name, measurement in case.scores.items() if measurement.weight != 1.0},
        error=case.error,
        skipped=case.skipped,
    )


def suite_status(result: SuiteResult, verdict: SuiteVerdict | None) -> SuiteStatus:
    if result.fully_skipped:
        return "skipped"
    if result.errors:
        return "errored"
    return "passed" if verdict is not None and verdict.passed else "failed"


def suite_report(
    result: SuiteResult,
    verdict: SuiteVerdict | None,
    thresholds: Thresholds,
    mode: RunMode,
    duration_seconds: float,
) -> SuiteReport:
    failures: Sequence[ThresholdFailure] = verdict.failures if verdict is not None else ()
    return SuiteReport(
        name=result.suite,
        status=suite_status(result, verdict),
        metrics=result.metrics,
        thresholds=applied_bounds(thresholds, result.suite, mode),
        ungated_metrics=list(verdict.ungated) if verdict is not None else [],
        failures=[failure.describe() for failure in failures],
        dataset_versions=dict(result.dataset_versions),
        cases=[case_report(case) for case in result.cases],
        measured_cases=result.measured,
        skipped_cases=result.skipped,
        errored_cases=result.errors,
        duration_seconds=round(duration_seconds, 2),
    )


def model_configuration(routing: RoutingConfig) -> dict[str, ModelRoute]:
    return {
        task.value: ModelRoute(primary=routing.route(task).primary, fallbacks=list(routing.route(task).fallbacks))
        for task in LlmTask
    }


def write_report(report: RunReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")


def scores_for_record(report: SuiteReport) -> Mapping[str, JsonValue]:
    return dict(report.metrics)
