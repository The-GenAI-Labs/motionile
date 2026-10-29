import argparse
import asyncio
import importlib
import logging
import sys
from collections.abc import Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import UUID

import structlog

from evals.browser import LocalBrowser, explicit_browser_environment
from evals.cassette import CASSETTES_ROOT, CassetteStore
from evals.clients import LiveSettings, LlmSessions
from evals.context import SuiteContext
from evals.datasets import load_datasets
from evals.errors import EvalAbortError, EvalError, OptionsError, ProviderKeysMissingError
from evals.metering import SpendMeter
from evals.modes import PromptSourceKind, RunMode, Selection, resolve_mode
from evals.prompts import FilePromptStore, OverridingPromptStore
from evals.recording import TRIGGERS, record_report
from evals.report import RunReport, model_configuration, suite_report, write_report
from evals.runner import EVALS_PACKAGE, Execution, discover_suites, run_suites, select_suites
from evals.thresholds import THRESHOLDS_PATH, Thresholds, load_thresholds
from motionile.core.config import AppEnv, Settings, get_settings
from motionile.engine.ai.llm.config import ProviderKeys
from motionile.engine.ai.llm.routing import DEFAULT_ROUTING
from motionile.engine.ai.ports import PromptStore

BUDGET_SETTING: Final = "evals.ci_live_budget_micros_usd"
EXIT_PASSED: Final = 0
EXIT_FAILED: Final = 1
EXIT_USAGE: Final = 2
EXIT_ABORTED: Final = 3


@dataclass(frozen=True, slots=True)
class RunOptions:
    suites: tuple[str, ...] | None = None
    mode: RunMode = RunMode.CASSETTE
    selection: Selection = Selection.FULL
    budget_micros: int | None = None
    output: Path | None = None
    record: bool = False
    trigger: str | None = None
    prompt_versions: tuple[UUID, ...] = ()
    prompts: PromptSourceKind = PromptSourceKind.FILES
    cassettes_dir: Path = CASSETTES_ROOT


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evals.run", description="Run the Motionile eval suites.")
    parser.add_argument("--suites", help="comma separated suite names; every suite by default")
    parser.add_argument("--mode", choices=[mode.value for mode in RunMode], default=RunMode.CASSETTE.value)
    parser.add_argument("--changed-ai", action="store_true", help="run the small subset for AI file changes")
    parser.add_argument("--budget-micros", type=int, help="live spend cap in millionths of a US dollar")
    parser.add_argument("--output", type=Path, help="write the JSON report here")
    parser.add_argument("--record", action="store_true", help="re-record cassettes from the scripted fake or live")
    parser.add_argument("--trigger", choices=sorted(TRIGGERS), help="record the results in eval_runs")
    parser.add_argument("--prompt-versions", help="comma separated prompt version ids to evaluate")
    parser.add_argument("--prompts", choices=[kind.value for kind in PromptSourceKind], default="files")
    parser.add_argument("--cassettes-dir", type=Path, default=CASSETTES_ROOT)
    return parser


def split_list(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    return [part.strip() for part in raw.split(",") if part.strip()]


def parse_uuids(values: Sequence[str]) -> tuple[UUID, ...]:
    try:
        return tuple(UUID(value) for value in values)
    except ValueError as error:
        raise OptionsError("--prompt-versions needs comma separated UUIDs") from error


def parse_options(argv: Sequence[str] | None) -> RunOptions:
    arguments = build_parser().parse_args(argv)
    suites = split_list(arguments.suites)
    versions = parse_uuids(split_list(arguments.prompt_versions) or [])
    if versions and arguments.prompts != PromptSourceKind.DATABASE.value:
        raise OptionsError("--prompt-versions needs --prompts database")
    return RunOptions(
        suites=tuple(suites) if suites is not None else None,
        mode=RunMode(arguments.mode),
        selection=Selection.CHANGED_AI if arguments.changed_ai else Selection.FULL,
        budget_micros=arguments.budget_micros,
        output=arguments.output,
        record=arguments.record,
        trigger=arguments.trigger,
        prompt_versions=versions,
        prompts=PromptSourceKind(arguments.prompts),
        cassettes_dir=arguments.cassettes_dir,
    )


def default_budget_micros() -> int:
    from motionile.modules.platform import SETTINGS  # noqa: PLC0415

    default = SETTINGS[BUDGET_SETTING].default
    if isinstance(default, bool) or not isinstance(default, int):
        raise OptionsError(f"the default of {BUDGET_SETTING} is not an integer")
    return default


@dataclass(frozen=True, slots=True)
class Assembly:
    options: RunOptions
    context: SuiteContext
    meter: SpendMeter
    prompt_version_ids: tuple[UUID, ...]
    prompt_source: PromptSourceKind


async def database_prompts(
    settings: Settings, stack: AsyncExitStack, versions: Sequence[UUID]
) -> tuple[PromptStore, tuple[UUID, ...]]:
    from motionile.core.db import Database, create_engine  # noqa: PLC0415
    from motionile.modules.prompts import DatabasePromptStore, prompts_under_evaluation  # noqa: PLC0415

    database = Database(create_engine(settings.database, application_name="motionile-evals"))
    stack.push_async_callback(database.dispose)
    base = DatabasePromptStore(database.transaction)
    if not versions:
        return base, tuple(prompt.version_id for prompt in await base.all_active())
    async with database.transaction() as session:
        candidates = await prompts_under_evaluation(session, versions)
    store = OverridingPromptStore(base, {prompt.key: prompt for prompt in candidates})
    return store, tuple(store.version_ids)


async def assemble(options: RunOptions, settings: Settings, stack: AsyncExitStack) -> Assembly:
    live = LiveSettings(keys=ProviderKeys(anthropic=settings.ai.anthropic_api_key, openai=settings.openai.api_key))
    mode = resolve_mode(options.mode, has_provider_keys=live.has_keys)
    if options.record and mode is RunMode.DETERMINISTIC:
        raise OptionsError("--record needs --mode cassette (scripted fake) or --mode live")
    if mode is RunMode.LIVE:
        live.require_keys()
    budget = options.budget_micros if options.budget_micros is not None else default_budget_micros()
    meter = SpendMeter(budget_micros=budget if mode is RunMode.LIVE else None)
    datasets = load_datasets()
    sessions = LlmSessions(
        mode=mode,
        meter=meter,
        datasets=datasets,
        cassettes=CassetteStore(options.cassettes_dir),
        record=options.record,
        live=live if mode is RunMode.LIVE else None,
    )
    prompts: PromptStore = FilePromptStore()
    version_ids: tuple[UUID, ...] = ()
    if options.prompts is PromptSourceKind.DATABASE:
        prompts, version_ids = await database_prompts(settings, stack, options.prompt_versions)
    context = SuiteContext(
        mode=mode,
        selection=options.selection,
        datasets=datasets,
        sessions=sessions,
        prompts=prompts,
        browser=LocalBrowser(explicit_browser_environment(settings)),
        allow_browser_skip=settings.app.env is AppEnv.LOCAL,
    )
    return Assembly(options, context, meter, version_ids, options.prompts)


def build_report(
    assembly: Assembly,
    execution: Execution,
    thresholds: Thresholds,
    started_at: datetime,
    error_code: str | None,
) -> RunReport:
    mode = assembly.context.mode
    options = assembly.options
    return RunReport(
        mode=mode,
        requested_mode=options.mode,
        selection=options.selection,
        trigger=options.trigger,
        recorded=options.record,
        prompt_source=assembly.prompt_source.value,
        prompt_version_ids=[str(version) for version in assembly.prompt_version_ids],
        started_at=started_at,
        finished_at=datetime.now(UTC),
        passed=execution.passed and error_code is None,
        error_code=error_code or (execution.aborted.code if execution.aborted else None),
        live_spend_micros_usd=assembly.meter.live_micros,
        budget_micros_usd=assembly.meter.budget_micros,
        model_configuration=model_configuration(DEFAULT_ROUTING),
        suites=[
            suite_report(run.result, run.verdict, thresholds, mode, run.duration_seconds) for run in execution.runs
        ],
    )


def print_report(report: RunReport, execution: Execution) -> None:
    out = sys.stdout
    out.write(
        f"mode: {report.mode.value} ({report.selection.value}), live spend {report.live_spend_micros_usd} micro-USD\n"
    )
    for suite in report.suites:
        if suite.status == "skipped":
            reasons = sorted({case.skipped for case in suite.cases if case.skipped})
            out.write(f"SKIP {suite.name}: {', '.join(reasons)}\n")
            continue
        scores = " ".join(f"{name}={value:.4f}" for name, value in suite.metrics.items())
        out.write(f"{suite.status.upper()} {suite.name} ({suite.measured_cases} cases): {scores}\n")
        for case in suite.cases:
            if case.error:
                out.write(f"ERROR {suite.name}.{case.id}: {case.error}\n")
        for failure in suite.failures:
            out.write(f"FAIL {failure}\n")
        if suite.ungated_metrics:
            out.write(f"note {suite.name}: not gated in this mode: {', '.join(suite.ungated_metrics)}\n")
    if execution.aborted is not None:
        out.write(f"ABORT {execution.aborted.code}: {execution.aborted}\n")
    failures = sum(len(suite.failures) for suite in report.suites)
    out.write(f"{len(report.suites)} suites evaluated, {failures} threshold failures.\n")


async def execute(options: RunOptions) -> int:
    suites = select_suites(discover_suites(importlib.import_module(EVALS_PACKAGE)), options.suites)
    if not suites:
        sys.stdout.write("No eval suites are registered yet.\n")
        return EXIT_PASSED
    thresholds = load_thresholds(THRESHOLDS_PATH)
    settings = get_settings()
    started_at = datetime.now(UTC)
    async with AsyncExitStack() as stack:
        assembly = await assemble(options, settings, stack)
        execution = await run_suites(assembly.context, suites, thresholds)
        report = build_report(assembly, execution, thresholds, started_at, None)
        if options.trigger is not None and execution.aborted is None:
            try:
                await record_report(settings, report, options.trigger, assembly.prompt_version_ids)
            except EvalError as error:
                report = build_report(assembly, execution, thresholds, started_at, error.code)
                sys.stdout.write(f"ABORT {error.code}: {error}\n")
        if options.output is not None:
            write_report(report, options.output)
        print_report(report, execution)
    if execution.aborted is not None or report.error_code is not None:
        return EXIT_ABORTED
    return EXIT_PASSED if report.passed else EXIT_FAILED


def quiet_logging() -> None:
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
        logger_factory=structlog.PrintLoggerFactory(sys.stderr),
    )


def main(argv: Sequence[str] | None = None) -> int:
    quiet_logging()
    try:
        options = parse_options(argv)
        return asyncio.run(execute(options))
    except EvalAbortError as error:
        sys.stdout.write(f"ABORT {error.code}: {error}\n")
        return EXIT_USAGE if isinstance(error, OptionsError | ProviderKeysMissingError) else EXIT_ABORTED


if __name__ == "__main__":
    sys.exit(main())
