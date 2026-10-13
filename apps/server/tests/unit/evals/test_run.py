import sys
import types
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError

import evals
from evals import run
from evals.run import EvalSuite, Metrics, ThresholdFailure, Thresholds, discover_suites, evaluate, load_thresholds

SAFETY_SUITE_SOURCE = """
class _Suite:
    name = "safety"

    def run(self):
        return {"blocked": 1.0}


SUITE = _Suite()
"""


@dataclass(frozen=True)
class StaticSuite:
    name: str
    metrics: dict[str, float]

    def run(self) -> Metrics:
        return self.metrics


def discovering(*suites: EvalSuite) -> Callable[[types.ModuleType], list[EvalSuite]]:
    def discover(_package: types.ModuleType) -> list[EvalSuite]:
        return list(suites)

    return discover


def loading(thresholds: Thresholds) -> Callable[[Path], Thresholds]:
    def load(_path: Path) -> Thresholds:
        return thresholds

    return load


def test_main_reports_no_suites_and_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    assert run.main() == 0
    assert "No eval suites are registered yet." in capsys.readouterr().out


def test_main_fails_when_a_registered_suite_misses_thresholds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(run, "discover_suites", discovering(StaticSuite("planner", {"accuracy": 0.5})))
    monkeypatch.setattr(run, "load_thresholds", loading({"planner": {"accuracy": 0.9}}))

    assert run.main() == 1
    assert "FAIL planner.accuracy" in capsys.readouterr().out


def test_main_succeeds_when_suites_meet_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run, "discover_suites", discovering(StaticSuite("planner", {"accuracy": 0.95})))
    monkeypatch.setattr(run, "load_thresholds", loading({"planner": {"accuracy": 0.9}}))

    assert run.main() == 0


def test_evaluate_reports_metrics_below_minimum_and_missing_metrics() -> None:
    suites: list[EvalSuite] = [StaticSuite("visual", {"overlap": 0.7})]

    failures = evaluate(suites, {"visual": {"overlap": 0.8, "contrast": 0.9}})

    assert failures == [
        ThresholdFailure("visual", "overlap", 0.8, 0.7),
        ThresholdFailure("visual", "contrast", 0.9, None),
    ]
    assert failures[0].describe() == "visual.overlap: 0.7000 is below the required 0.8000"
    assert failures[1].describe() == "visual.contrast: missing is below the required 0.9000"


def test_evaluate_passes_suites_without_thresholds() -> None:
    suites: list[EvalSuite] = [StaticSuite("captions", {"length": 0.1})]

    assert evaluate(suites, {}) == []


def test_discover_suites_finds_packages_exposing_a_suite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package_root = tmp_path / "fake_evals"
    (package_root / "safety").mkdir(parents=True)
    (package_root / "unregistered").mkdir()
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "helpers.py").write_text("", encoding="utf-8")
    (package_root / "safety" / "__init__.py").write_text(SAFETY_SUITE_SOURCE, encoding="utf-8")
    (package_root / "unregistered" / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "path", [str(tmp_path), *sys.path])
    package = types.ModuleType("fake_evals")
    package.__path__ = [str(package_root)]

    suites = discover_suites(package)

    assert [suite.name for suite in suites] == ["safety"]


def test_discover_suites_returns_nothing_for_the_real_package() -> None:
    assert discover_suites(evals) == []


def test_load_thresholds_reads_suite_minimums(tmp_path: Path) -> None:
    path = tmp_path / "thresholds.yaml"
    path.write_text("suites:\n  planner:\n    accuracy: 0.9\n", encoding="utf-8")

    assert load_thresholds(path) == {"planner": {"accuracy": 0.9}}


def test_load_thresholds_accepts_the_committed_file() -> None:
    assert load_thresholds(run.THRESHOLDS_PATH) == {}


@pytest.mark.parametrize("content", ["- not\n- a mapping\n", "suites:\n  - planner\n", "unknown: 1\n"])
def test_load_thresholds_rejects_malformed_documents(tmp_path: Path, content: str) -> None:
    path = tmp_path / "thresholds.yaml"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ValidationError):
        load_thresholds(path)
