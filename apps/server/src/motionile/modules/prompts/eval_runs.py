from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import Clock
from motionile.core.pagination import Cursor
from motionile.modules.prompts.auditing import audit
from motionile.modules.prompts.domain import (
    AUDIT_RUN_TARGET,
    DATASET_VERSION_FORMAT,
    ERROR_CODE_FORMAT,
    MAX_RUN_VERSIONS,
    PENDING_DATASET_VERSION,
    SUITE_FORMAT,
    Actor,
    EvalStatus,
    PromptAction,
    RunStatus,
    RunTrigger,
    Subject,
)
from motionile.modules.prompts.exceptions import (
    EvalRunInvalidError,
    EvalRunNotFoundError,
    PromptVersionNotFoundError,
    UnknownSuiteError,
)
from motionile.modules.prompts.executor import EvalOutcome
from motionile.modules.prompts.gate import KNOWN_SUITES, ActivationGate
from motionile.modules.prompts.models import EvalRun
from motionile.modules.prompts.repository import (
    NewRun,
    PromptRepository,
    RunFilter,
    RunResult,
    SqlPromptRepository,
    StoreFactory,
    Transaction,
)
from motionile.modules.prompts.schemas import EvalRunView
from motionile.modules.prompts.views import eval_run_view

MAX_RECORDED_VERSIONS = 100

type EnqueueEval = Callable[[AsyncSession, UUID], None]


@dataclass(frozen=True, slots=True)
class EvalRunListing:
    items: list[EvalRunView]
    next_cursor: Cursor | None


@dataclass(frozen=True, slots=True)
class ExternalRun:
    suite: str
    trigger: RunTrigger
    dataset_version: str
    prompt_version_ids: Sequence[UUID]
    model_configuration: Mapping[str, Any]
    scores: Mapping[str, Any]
    passed: bool
    started_at: datetime
    finished_at: datetime
    error_code: str | None = None


def ensure_suite(suite: str) -> None:
    if SUITE_FORMAT.fullmatch(suite) is None:
        raise EvalRunInvalidError("The suite name is invalid.")


def ensure_dataset_version(dataset_version: str) -> None:
    if DATASET_VERSION_FORMAT.fullmatch(dataset_version) is None:
        raise EvalRunInvalidError("The dataset version is invalid.")


def ensure_outcome(outcome: EvalOutcome) -> None:
    ensure_dataset_version(outcome.dataset_version)


async def refresh_eval_statuses(
    session: AsyncSession, repository: PromptRepository, gate: ActivationGate, version_ids: Sequence[UUID]
) -> None:
    for version in await repository.versions_by_ids(list(version_ids)):
        verdict = await gate.check(session, version.id)
        if verdict.complete:
            status = EvalStatus.PASSED if verdict.activatable else EvalStatus.FAILED
            await repository.set_eval_result(version.id, status.value, verdict.report())


async def record_external_run(
    session: AsyncSession, run: ExternalRun, *, store_factory: StoreFactory = SqlPromptRepository
) -> UUID:
    ensure_suite(run.suite)
    ensure_dataset_version(run.dataset_version)
    if run.trigger is RunTrigger.ADMIN:
        raise EvalRunInvalidError("Admin runs are started through the console.")
    if len(run.prompt_version_ids) > MAX_RECORDED_VERSIONS:
        raise EvalRunInvalidError("A run can cover at most 100 prompt versions.")
    if run.error_code is not None and ERROR_CODE_FORMAT.fullmatch(run.error_code) is None:
        raise EvalRunInvalidError("The error code is invalid.")
    repository = store_factory(session)
    failed = run.error_code is not None
    stored = await repository.insert_run(
        NewRun(
            suite=run.suite,
            dataset_version=run.dataset_version,
            prompt_version_ids=list(dict.fromkeys(run.prompt_version_ids)),
            trigger=run.trigger.value,
            created_by=None,
            status=RunStatus.ERRORED if failed else RunStatus.FINISHED,
            models_used=run.model_configuration,
            scores=run.scores,
            passed=None if failed else run.passed,
            error_code=run.error_code,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )
    )
    await audit(
        session,
        None,
        PromptAction.EVAL_RECORDED,
        Subject(AUDIT_RUN_TARGET, stored.id),
        {
            "suite": run.suite,
            "trigger": run.trigger.value,
            "passed": None if failed else run.passed,
            "version_count": len(stored.prompt_version_ids),
        },
    )
    if not failed:
        await refresh_eval_statuses(session, repository, ActivationGate(store_factory), stored.prompt_version_ids)
    return stored.id


class EvalRunService:
    def __init__(
        self,
        *,
        transaction: Transaction,
        store_factory: StoreFactory,
        gate: ActivationGate,
        clock: Clock,
        enqueue: EnqueueEval,
    ) -> None:
        self._transaction = transaction
        self._store_factory = store_factory
        self._gate = gate
        self._clock = clock
        self._enqueue = enqueue

    async def start(self, session: AsyncSession, actor: Actor, suite: str, version_ids: Sequence[UUID]) -> EvalRun:
        if suite not in KNOWN_SUITES:
            raise UnknownSuiteError
        unique = list(dict.fromkeys(version_ids))
        if not 0 < len(unique) <= MAX_RUN_VERSIONS:
            raise EvalRunInvalidError(f"A run covers between 1 and {MAX_RUN_VERSIONS} prompt versions.")
        repository = self._store_factory(session)
        if len(await repository.versions_by_ids(unique)) != len(unique):
            raise PromptVersionNotFoundError
        run = await repository.insert_run(
            NewRun(
                suite=suite,
                dataset_version=PENDING_DATASET_VERSION,
                prompt_version_ids=unique,
                trigger=RunTrigger.ADMIN.value,
                created_by=actor.user_id,
            )
        )
        await audit(
            session,
            actor,
            PromptAction.EVAL_STARTED,
            Subject(AUDIT_RUN_TARGET, run.id),
            {"suite": suite, "version_ids": [str(version_id) for version_id in unique]},
        )
        self._enqueue(session, run.id)
        return run

    async def start_run(self, actor: Actor, suite: str, version_ids: Sequence[UUID]) -> EvalRunView:
        async with self._transaction() as session:
            return eval_run_view(await self.start(session, actor, suite, version_ids))

    async def get(self, run_id: UUID) -> EvalRunView:
        async with self._transaction() as session:
            run = await self._store_factory(session).run(run_id)
        if run is None:
            raise EvalRunNotFoundError
        return eval_run_view(run)

    async def running(self, run_id: UUID) -> EvalRunView | None:
        async with self._transaction() as session:
            run = await self._store_factory(session).run(run_id)
        if run is None or run.status != RunStatus.RUNNING.value:
            return None
        return eval_run_view(run)

    async def page(self, run_filter: RunFilter, cursor: Cursor | None, limit: int) -> EvalRunListing:
        async with self._transaction() as session:
            rows = await self._store_factory(session).page_runs(run_filter, cursor, limit)
        shown = rows[:limit]
        next_cursor = Cursor(shown[-1].created_at, shown[-1].id) if len(rows) > limit and shown else None
        return EvalRunListing([eval_run_view(row) for row in shown], next_cursor)

    async def finish(self, run_id: UUID, outcome: EvalOutcome) -> bool:
        ensure_outcome(outcome)
        result = RunResult(
            dataset_version=outcome.dataset_version,
            models_used=outcome.model_configuration,
            scores=outcome.scores,
            passed=outcome.passed,
        )
        async with self._transaction() as session:
            repository = self._store_factory(session)
            if not await repository.finish_run(run_id, result, self._clock.now()):
                return False
            run = await repository.run(run_id)
            if run is not None:
                await refresh_eval_statuses(session, repository, self._gate, run.prompt_version_ids)
        return True

    async def fail(self, run_id: UUID, error_code: str) -> bool:
        if ERROR_CODE_FORMAT.fullmatch(error_code) is None:
            raise EvalRunInvalidError("The error code is invalid.")
        async with self._transaction() as session:
            return await self._store_factory(session).fail_run(run_id, error_code, self._clock.now())
