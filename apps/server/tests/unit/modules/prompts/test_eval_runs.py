import asyncio
from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta
from typing import cast
from uuid import UUID

import pytest
from tests.fakes.prompts import assert_run_consistent
from tests.unit.modules.prompts.support import ACTOR, KEY, Harness, build_harness

from motionile.core.ids import new_id
from motionile.core.resources import Resources
from motionile.modules.prompts import (
    EvalExecutionError,
    EvalExecutor,
    EvalOutcome,
    ExternalRun,
    install_eval_executor,
    record_external_run,
)
from motionile.modules.prompts.domain import RunTrigger
from motionile.modules.prompts.exceptions import (
    EvalRunInvalidError,
    EvalRunNotFoundError,
    PromptVersionNotFoundError,
    UnknownSuiteError,
)
from motionile.modules.prompts.executor import eval_executor_for
from motionile.modules.prompts.gate import REQUIRED_SUITES
from motionile.modules.prompts.models import EvalRun
from motionile.modules.prompts.repository import RunFilter
from motionile.modules.prompts.runner import EvalRunner


class ScriptedExecutor:
    def __init__(self, outcome: EvalOutcome | Exception | None = None, delay: float = 0.0) -> None:
        self.outcome = outcome or EvalOutcome({"accuracy": 0.97}, True, "2026.10", {"planner": "fake-model"})
        self.delay = delay
        self.calls: list[tuple[UUID, str, tuple[UUID, ...]]] = []

    async def execute(self, run_id: UUID, suite: str, version_ids: Sequence[UUID]) -> EvalOutcome:
        self.calls.append((run_id, suite, tuple(version_ids)))
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def runner_for(harness: Harness, executor: ScriptedExecutor | None, timeout: float = 5.0) -> EvalRunner:
    def source() -> EvalExecutor | None:
        return executor

    return EvalRunner(harness.evals, source, timeout_seconds=timeout)


@pytest.fixture
async def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    built = build_harness(monkeypatch)
    await built.seed()
    return built


async def start(harness: Harness, suite: str = "planner") -> UUID:
    view = await harness.evals.start_run(ACTOR, suite, [harness.version().id])
    return view.id


def stored(harness: Harness, run_id: UUID) -> EvalRun:
    run = harness.world.runs[run_id]
    assert_run_consistent(run)
    return run


async def test_starting_a_run_creates_a_running_row_and_defers_the_task_once(harness: Harness) -> None:
    version = harness.version()

    view = await harness.evals.start_run(ACTOR, "planner", [version.id, version.id])

    run = stored(harness, view.id)
    assert (run.status, run.trigger, run.created_by, run.passed) == ("running", "admin", ACTOR.user_id, None)
    assert (run.suite, run.dataset_version, run.prompt_version_ids) == ("planner", "pending", [version.id])
    assert run.finished_at is None
    assert harness.enqueued == [view.id]
    [event] = [event for event in harness.audit if event.action == "prompts.eval_started"]
    assert event.target_type == "eval_run"
    assert event.actor_user_id == ACTOR.user_id


async def test_unknown_suites_versions_and_empty_selections_are_rejected(harness: Harness) -> None:
    with pytest.raises(UnknownSuiteError):
        await harness.evals.start_run(ACTOR, "made_up", [harness.version().id])
    with pytest.raises(PromptVersionNotFoundError):
        await harness.evals.start_run(ACTOR, "planner", [new_id()])
    with pytest.raises(EvalRunInvalidError):
        await harness.evals.start_run(ACTOR, "planner", [])
    assert harness.enqueued == []
    assert harness.world.runs == {}


async def test_the_runner_finishes_the_run_with_the_executor_outcome(harness: Harness) -> None:
    run_id = await start(harness)
    executor = ScriptedExecutor()

    await runner_for(harness, executor).run(run_id)

    run = stored(harness, run_id)
    assert (run.status, run.passed, run.dataset_version) == ("finished", True, "2026.10")
    assert run.scores == {"accuracy": 0.97}
    assert run.models_used == {"planner": "fake-model"}
    assert run.finished_at == harness.world.clock.now()
    assert executor.calls == [(run_id, "planner", (harness.version().id,))]


async def test_a_finished_run_is_not_executed_again(harness: Harness) -> None:
    run_id = await start(harness)
    executor = ScriptedExecutor()
    runner = runner_for(harness, executor)

    await runner.run(run_id)
    await runner.run(run_id)

    assert len(executor.calls) == 1


async def test_a_missing_run_is_skipped(harness: Harness) -> None:
    executor = ScriptedExecutor()

    await runner_for(harness, executor).run(new_id())

    assert executor.calls == []


@pytest.mark.parametrize(
    ("outcome", "code"),
    [
        (EvalExecutionError("dataset_missing"), "dataset_missing"),
        (EvalExecutionError("Bad Code"), "eval_executor_failed"),
        (RuntimeError("provider exploded"), "eval_executor_failed"),
        (EvalOutcome({}, True, "not valid!", {}), "eval_outcome_invalid"),
    ],
)
async def test_executor_problems_mark_the_run_errored_with_a_stable_code(
    harness: Harness, outcome: EvalOutcome | Exception, code: str
) -> None:
    run_id = await start(harness)

    await runner_for(harness, ScriptedExecutor(outcome)).run(run_id)

    run = stored(harness, run_id)
    assert (run.status, run.error_code, run.passed) == ("errored", code, None)


async def test_a_slow_executor_times_out(harness: Harness) -> None:
    run_id = await start(harness)

    await runner_for(harness, ScriptedExecutor(delay=1.0), timeout=0.01).run(run_id)

    assert stored(harness, run_id).error_code == "eval_timeout"


async def test_without_an_installed_executor_the_run_errors(harness: Harness) -> None:
    run_id = await start(harness)

    await runner_for(harness, None).run(run_id)

    run = stored(harness, run_id)
    assert (run.status, run.error_code) == ("errored", "eval_executor_unavailable")


def test_the_executor_is_installed_and_removed_through_the_provider() -> None:
    resources = cast("Resources", object())
    executor = ScriptedExecutor()
    assert eval_executor_for(resources) is None

    install_eval_executor(lambda _: executor)
    try:
        assert eval_executor_for(resources) is executor
    finally:
        install_eval_executor(None)

    assert eval_executor_for(resources) is None


async def test_version_status_follows_the_required_suites(harness: Harness) -> None:
    version = harness.version()
    suites = REQUIRED_SUITES[KEY]
    for suite in suites[:-1]:
        run_id = await start(harness, suite)
        await runner_for(harness, ScriptedExecutor()).run(run_id)
    assert (version.eval_status, version.eval_report) == ("pending", None)

    run_id = await start(harness, suites[-1])
    await runner_for(harness, ScriptedExecutor()).run(run_id)

    assert version.eval_status == "passed"
    assert version.eval_report is not None
    assert [entry["suite"] for entry in version.eval_report["passed"]] == list(suites)


async def test_a_failing_required_suite_marks_the_version_failed_once_all_suites_ran(harness: Harness) -> None:
    version = harness.version()
    failing = EvalOutcome({"accuracy": 0.2}, False, "2026.10", {})
    suites = REQUIRED_SUITES[KEY]
    for suite in suites:
        run_id = await start(harness, suite)
        await runner_for(harness, ScriptedExecutor(failing if suite == "cost" else None)).run(run_id)

    assert version.eval_status == "failed"
    assert version.eval_report is not None
    assert version.eval_report["failed"] == ["cost"]

    rerun = await start(harness, "cost")
    await runner_for(harness, ScriptedExecutor()).run(rerun)

    assert version.eval_status == "passed"


async def test_runs_are_read_and_listed_with_filters_and_a_cursor(harness: Harness) -> None:
    first = await start(harness, "planner")
    second = await start(harness, "safety")
    await runner_for(harness, ScriptedExecutor()).run(first)

    assert (await harness.evals.get(second)).status.value == "running"
    with pytest.raises(EvalRunNotFoundError):
        await harness.evals.get(new_id())
    everything = await harness.evals.page(RunFilter(), None, 1)
    assert [item.id for item in everything.items] == [second]
    assert everything.next_cursor is not None
    older = await harness.evals.page(RunFilter(), everything.next_cursor, 1)
    assert [item.id for item in older.items] == [first]
    assert older.next_cursor is None
    assert [item.id for item in (await harness.evals.page(RunFilter(suite="planner"), None, 5)).items] == [first]
    assert [item.id for item in (await harness.evals.page(RunFilter(status="running"), None, 5)).items] == [second]


async def test_external_runs_are_recorded_and_can_complete_a_version(harness: Harness) -> None:
    version = harness.version()
    started = harness.world.clock.now() + timedelta(seconds=1)
    for suite in REQUIRED_SUITES[KEY]:
        async with harness.world.transaction() as session:
            run_id = await record_external_run(
                session,
                ExternalRun(
                    suite=suite,
                    trigger=RunTrigger.NIGHTLY,
                    dataset_version="2026.10",
                    prompt_version_ids=[version.id],
                    model_configuration={"planner": "model"},
                    scores={"accuracy": 1.0},
                    passed=True,
                    started_at=started,
                    finished_at=started + timedelta(seconds=5),
                ),
                store_factory=harness.world.store,
            )
        run = stored(harness, run_id)
        assert (run.status, run.trigger, run.created_by) == ("finished", "nightly", None)

    assert version.eval_status == "passed"
    assert len([event for event in harness.audit if event.action == "prompts.eval_recorded"]) == len(
        REQUIRED_SUITES[KEY]
    )


async def test_an_errored_external_run_never_changes_version_status(harness: Harness) -> None:
    version = harness.version()
    started = harness.world.clock.now() + timedelta(seconds=1)

    async with harness.world.transaction() as session:
        run_id = await record_external_run(
            session,
            ExternalRun(
                suite="planner",
                trigger=RunTrigger.CI,
                dataset_version="2026.10",
                prompt_version_ids=[version.id],
                model_configuration={},
                scores={},
                passed=True,
                started_at=started,
                finished_at=started,
                error_code="dataset_missing",
            ),
            store_factory=harness.world.store,
        )

    run = stored(harness, run_id)
    assert (run.status, run.passed, run.error_code) == ("errored", None, "dataset_missing")
    assert version.eval_status == "pending"


@pytest.mark.parametrize(
    "changes",
    [
        {"trigger": RunTrigger.ADMIN},
        {"suite": "Bad Suite"},
        {"dataset_version": "!"},
        {"error_code": "Not A Code"},
        {"prompt_version_ids": [new_id() for _ in range(101)]},
    ],
)
async def test_invalid_external_runs_are_refused(harness: Harness, changes: dict[str, object]) -> None:
    started = harness.world.clock.now()
    valid = ExternalRun(
        suite="planner",
        trigger=RunTrigger.CI,
        dataset_version="2026.10",
        prompt_version_ids=[harness.version().id],
        model_configuration={},
        scores={},
        passed=True,
        started_at=started,
        finished_at=started,
    )

    with pytest.raises(EvalRunInvalidError):
        async with harness.world.transaction() as session:
            await record_external_run(session, replace(valid, **changes), store_factory=harness.world.store)

    assert harness.world.runs == {}
