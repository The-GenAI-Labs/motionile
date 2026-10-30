import json
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest

import evals
from evals import run
from evals.browser import LocalBrowser
from evals.cassette import CassetteStore
from evals.clients import LlmSessions
from evals.context import EvalSuite, SuiteContext
from evals.datasets import load_datasets
from evals.errors import EvalBudgetExceededError, OptionsError, UnknownSuiteError
from evals.metering import SpendMeter
from evals.modes import RunMode, Selection
from evals.prompts import FilePromptStore
from evals.results import CaseResult, Measurement, SuiteResult
from evals.runner import discover_suites, run_suites, select_suites
from evals.thresholds import Bound, MetricThreshold
from motionile.engine.ai.llm.models import LlmTask

SAFETY_SUITE_SOURCE = """
class _Suite:
    name = "safety"

    async def run(self, context):
        return None


SUITE = _Suite()
"""


@dataclass(frozen=True)
class StaticSuite:
    name: str
    metrics: dict[str, float]

    async def run(self, context: SuiteContext) -> SuiteResult:
        del context
        scores = {metric: Measurement(value) for metric, value in self.metrics.items()}
        return SuiteResult(self.name, (CaseResult("case-1", scores),), {"golden": "2026-10-24.1"})


@dataclass(frozen=True)
class AbortingSuite:
    name: str

    async def run(self, context: SuiteContext) -> SuiteResult:
        del context
        raise EvalBudgetExceededError("over budget")


def suite_context(mode: RunMode = RunMode.DETERMINISTIC) -> SuiteContext:
    datasets = load_datasets()
    sessions = LlmSessions(mode=mode, meter=SpendMeter(), datasets=datasets, cassettes=CassetteStore())
    return SuiteContext(
        mode=mode,
        selection=Selection.FULL,
        datasets=datasets,
        sessions=sessions,
        prompts=FilePromptStore(),
        browser=LocalBrowser(),
    )


def thresholds_file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "thresholds.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_discovery_finds_every_package_that_exposes_a_suite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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

    assert [suite.name for suite in discover_suites(package)] == ["safety"]


def test_the_real_package_registers_the_five_suites() -> None:
    assert [suite.name for suite in discover_suites(evals)] == ["cost", "planner", "safety", "scenes", "sync"]


def test_selecting_unknown_suites_is_a_usage_error() -> None:
    available: list[EvalSuite] = [StaticSuite("planner", {})]

    with pytest.raises(UnknownSuiteError, match="unknown suites: nope"):
        select_suites(available, ["planner", "nope"])
    assert [suite.name for suite in select_suites(available, ["planner", "planner"])] == ["planner"]
    assert select_suites(available, None) == available


async def test_a_passing_suite_has_a_verdict_and_a_duration() -> None:
    thresholds = {"planner": {"accuracy": MetricThreshold(default=Bound(min=0.9))}}

    execution = await run_suites(suite_context(), [StaticSuite("planner", {"accuracy": 0.95})], thresholds)

    assert execution.passed
    verdict = execution.runs[0].verdict
    assert verdict is not None
    assert verdict.gated == ("accuracy",)


async def test_a_regression_below_a_minimum_fails_the_execution() -> None:
    thresholds = {"planner": {"accuracy": MetricThreshold(default=Bound(min=0.9))}}

    execution = await run_suites(suite_context(), [StaticSuite("planner", {"accuracy": 0.5})], thresholds)

    assert not execution.passed


async def test_a_value_above_a_maximum_fails_the_execution() -> None:
    thresholds = {"cost": {"tokens": MetricThreshold(default=Bound(max=100))}}

    execution = await run_suites(suite_context(), [StaticSuite("cost", {"tokens": 101})], thresholds)

    assert not execution.passed


async def test_an_abort_stops_the_remaining_suites_and_keeps_the_finished_ones() -> None:
    suites: list[EvalSuite] = [StaticSuite("cost", {}), AbortingSuite("planner"), StaticSuite("safety", {})]

    execution = await run_suites(suite_context(), suites, {})

    assert [run.result.suite for run in execution.runs] == ["cost"]
    assert execution.aborted is not None
    assert execution.aborted.code == "eval_budget_exceeded"
    assert not execution.passed


def test_options_default_to_cassette_mode_and_every_suite() -> None:
    options = run.parse_options([])

    assert options.mode is RunMode.CASSETTE
    assert options.suites is None
    assert options.selection is Selection.FULL
    assert not options.record


def test_options_parse_every_flag() -> None:
    identifier = uuid4()

    options = run.parse_options(
        [
            "--suites=planner,safety",
            "--mode=auto",
            "--changed-ai",
            "--budget-micros=1500",
            "--output=out.json",
            "--record",
            "--trigger=nightly",
            "--prompts=database",
            f"--prompt-versions={identifier}",
        ]
    )

    assert options.suites == ("planner", "safety")
    assert options.mode is RunMode.AUTO
    assert options.selection is Selection.CHANGED_AI
    assert options.budget_micros == 1500
    assert options.output == Path("out.json")
    assert options.record
    assert options.trigger == "nightly"
    assert options.prompt_versions == (identifier,)


def test_prompt_versions_need_the_database_prompt_source() -> None:
    with pytest.raises(OptionsError, match="--prompts database"):
        run.parse_options([f"--prompt-versions={uuid4()}"])


def test_prompt_versions_must_be_uuids() -> None:
    with pytest.raises(OptionsError, match="UUIDs"):
        run.parse_options(["--prompts=database", "--prompt-versions=not-a-uuid"])


def test_admin_runs_cannot_be_recorded_from_the_command_line() -> None:
    with pytest.raises(SystemExit):
        run.parse_options(["--trigger=admin"])


def test_the_default_budget_is_the_platform_setting_default() -> None:
    assert run.default_budget_micros() == 2_000_000


def test_main_runs_a_suite_in_deterministic_mode_and_writes_the_report(tmp_path: Path) -> None:
    output = tmp_path / "results.json"

    code = run.main(["--mode=deterministic", "--suites=safety", "--changed-ai", f"--output={output}"])

    report = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert report["mode"] == "deterministic"
    assert report["selection"] == "changed_ai"
    assert report["passed"] is True
    assert report["liveSpendMicrosUsd"] == 0
    (suite,) = report["suites"]
    assert suite["name"] == "safety"
    assert suite["status"] == "passed"
    assert suite["metrics"]["refusal_accuracy"] == 1.0
    assert suite["thresholds"]["leak_free_outputs"] == {"min": 1.0}
    assert suite["datasetVersions"] == {"adversarial": "2026-10-24.1"}
    assert suite["measuredCases"] == len(suite["cases"]) == 12
    assert set(report["modelConfiguration"]) == {task.value for task in LlmTask}


def test_main_fails_and_prints_each_regression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = thresholds_file(
        tmp_path,
        "suites:\n  safety:\n    refusal_accuracy:\n      default: { min: 1.5 }\n"
        "    false_refusal_rate:\n      default: { max: -1 }\n",
    )
    monkeypatch.setattr(run, "THRESHOLDS_PATH", path)

    code = run.main(["--mode=deterministic", "--suites=safety", "--changed-ai"])

    printed = capsys.readouterr().out
    assert code == 1
    assert "FAIL safety.refusal_accuracy: 1.0000 is below the required minimum 1.5000" in printed
    assert "FAIL safety.false_refusal_rate: 0.0000 is above the allowed maximum -1.0000" in printed


def test_main_reports_unknown_suites_as_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert run.main(["--suites=nope"]) == 2
    assert "eval_unknown_suite" in capsys.readouterr().out


def test_live_mode_refuses_to_run_without_provider_keys(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("AI_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    code = run.main(["--mode=live", "--suites=safety"])

    assert code == 2
    assert "eval_keys_missing" in capsys.readouterr().out


def test_recording_needs_a_mode_with_a_source(capsys: pytest.CaptureFixture[str]) -> None:
    assert run.main(["--mode=deterministic", "--record"]) == 2
    assert "--record" in capsys.readouterr().out


def test_cassette_mode_fails_closed_when_a_recording_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run.main(["--mode=cassette", "--suites=safety", "--changed-ai", f"--cassettes-dir={tmp_path}"])

    assert code == 3
    assert "ABORT cassette_miss" in capsys.readouterr().out


def test_recording_then_replaying_gives_the_same_scores(tmp_path: Path) -> None:
    recorded = tmp_path / "recorded.json"
    replayed = tmp_path / "replayed.json"
    arguments = ["--mode=cassette", "--suites=safety", "--changed-ai", f"--cassettes-dir={tmp_path / 'cassettes'}"]

    assert run.main([*arguments, "--record", f"--output={recorded}"]) == 0
    assert run.main([*arguments, f"--output={replayed}"]) == 0

    first = json.loads(recorded.read_text(encoding="utf-8"))
    second = json.loads(replayed.read_text(encoding="utf-8"))
    assert first["suites"][0]["metrics"] == second["suites"][0]["metrics"]
    assert first["suites"][0]["metrics"]["refusal_accuracy"] == 1.0
    assert (tmp_path / "cassettes" / "safety" / "inj-direct-01.json").is_file()
    assert (tmp_path / "cassettes" / "safety" / "inj-direct-01-probe.json").is_file()
