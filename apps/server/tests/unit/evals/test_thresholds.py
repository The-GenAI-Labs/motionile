from pathlib import Path

import pytest
from pydantic import ValidationError

from evals.errors import ThresholdsError
from evals.modes import RunMode
from evals.results import CaseResult, Measurement, SuiteResult
from evals.thresholds import (
    THRESHOLDS_PATH,
    Bound,
    MetricThreshold,
    ThresholdFailure,
    applied_bounds,
    judge_suite,
    judge_suites,
    load_thresholds,
)


def result(suite: str = "planner", **metrics: float) -> SuiteResult:
    scores = {name: Measurement(value) for name, value in metrics.items()}
    return SuiteResult(suite, (CaseResult("case-1", scores),), {"golden": "2026-10-24.1"})


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_a_metric_below_its_minimum_fails_with_a_readable_message() -> None:
    thresholds = {"planner": {"accuracy": MetricThreshold(default=Bound(min=0.9))}}

    verdict = judge_suite(result(accuracy=0.7), thresholds, RunMode.CASSETTE)

    assert verdict.failures == (ThresholdFailure("planner", "accuracy", "min", 0.9, 0.7),)
    assert verdict.failures[0].describe() == "planner.accuracy: 0.7000 is below the required minimum 0.9000"
    assert not verdict.passed


def test_a_metric_above_its_maximum_fails_with_a_readable_message() -> None:
    thresholds = {"cost": {"tokens": MetricThreshold(default=Bound(max=1000))}}

    verdict = judge_suite(result("cost", tokens=1500), thresholds, RunMode.CASSETTE)

    assert verdict.failures[0].describe() == "cost.tokens: 1500.0000 is above the allowed maximum 1000.0000"


def test_a_metric_within_both_bounds_passes() -> None:
    thresholds = {"cost": {"tokens": MetricThreshold(default=Bound(min=10, max=100))}}

    assert judge_suite(result("cost", tokens=50), thresholds, RunMode.LIVE).passed


def test_a_declared_metric_that_was_not_measured_fails() -> None:
    thresholds = {"planner": {"accuracy": MetricThreshold(default=Bound(min=0.5))}}

    verdict = judge_suite(result(other=1.0), thresholds, RunMode.CASSETTE)

    assert verdict.failures[0].describe() == "planner.accuracy: not measured, min 0.5000 required"


def test_a_suite_without_thresholds_passes() -> None:
    assert judge_suite(result(accuracy=0.1), {}, RunMode.CASSETTE).passed


def test_mode_specific_bounds_override_the_default() -> None:
    threshold = MetricThreshold(default=Bound(min=0.9), live=Bound(min=0.5))
    thresholds = {"planner": {"accuracy": threshold}}

    assert not judge_suite(result(accuracy=0.6), thresholds, RunMode.CASSETTE).passed
    assert judge_suite(result(accuracy=0.6), thresholds, RunMode.LIVE).passed


def test_a_metric_without_a_bound_in_the_mode_is_reported_as_not_gated() -> None:
    thresholds = {"planner": {"accuracy": MetricThreshold(cassette=Bound(min=0.9))}}

    verdict = judge_suite(result(accuracy=0.1), thresholds, RunMode.DETERMINISTIC)

    assert verdict.passed
    assert verdict.ungated == ("accuracy",)
    assert verdict.gated == ()


def test_fully_skipped_suites_are_not_judged() -> None:
    skipped = SuiteResult("scenes", (CaseResult("a", skipped="chromium_unavailable"),), {})
    thresholds = {"scenes": {"fallback_rate": MetricThreshold(default=Bound(max=0.1))}}

    assert judge_suites([skipped], thresholds, RunMode.DETERMINISTIC) == []


def test_applied_bounds_lists_the_limits_for_the_mode() -> None:
    thresholds = {"cost": {"tokens": MetricThreshold(default=Bound(max=10), live=Bound(min=1, max=20))}}

    assert applied_bounds(thresholds, "cost", RunMode.CASSETTE) == {"tokens": {"max": 10}}
    assert applied_bounds(thresholds, "cost", RunMode.LIVE) == {"tokens": {"min": 1, "max": 20}}


def test_the_committed_file_loads_and_covers_the_five_suites() -> None:
    thresholds = load_thresholds(THRESHOLDS_PATH)

    assert set(thresholds) == {"planner", "scenes", "sync", "safety", "cost"}


def test_load_thresholds_reads_both_bound_kinds(tmp_path: Path) -> None:
    path = write(tmp_path / "t.yaml", "suites:\n  cost:\n    tokens:\n      default: { min: 1, max: 5 }\n")

    bound = load_thresholds(path)["cost"]["tokens"].bound_for(RunMode.CASSETTE)

    assert bound == Bound(min=1, max=5)


@pytest.mark.parametrize(
    "content",
    [
        "- not\n- a mapping\n",
        "suites:\n  - planner\n",
        "unknown: 1\n",
        "suites:\n  planner:\n    accuracy: 0.9\n",
        "suites:\n  planner:\n    accuracy: {}\n",
        "suites:\n  planner:\n    accuracy:\n      default: { min: 5, max: 1 }\n",
        "suites:\n  planner:\n    accuracy:\n      default: {}\n",
        "suites:\n  planner:\n    accuracy:\n      weird: { min: 1 }\n",
    ],
)
def test_malformed_threshold_files_are_rejected(tmp_path: Path, content: str) -> None:
    with pytest.raises(ThresholdsError):
        load_thresholds(write(tmp_path / "t.yaml", content))


def test_a_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ThresholdsError, match="cannot be read"):
        load_thresholds(tmp_path / "missing.yaml")


def test_a_bound_needs_at_least_one_limit() -> None:
    with pytest.raises(ValidationError):
        Bound()
