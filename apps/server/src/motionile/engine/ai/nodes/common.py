import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Final
from uuid import UUID

from motionile.engine.ai.graphs.deps import MS_PER_SECOND, PipelineDependencies
from motionile.engine.ai.graphs.errors import (
    InvalidTransitionError,
    JobCancelled,
    JobEnded,
    MissingJobIdError,
    PipelineError,
    PipelineErrorCode,
    pipeline_error,
)
from motionile.engine.ai.graphs.events import EventType, emit
from motionile.engine.ai.graphs.stages import STAGE_STATUS, Stage
from motionile.engine.ai.graphs.state import PipelineState
from motionile.engine.ai.job_options import JobStatus
from motionile.engine.ai.llm.models import CallContext, LlmError
from motionile.engine.ai.ports import JobSnapshot

ERROR_PRIORITY: Final[tuple[type[BaseException], ...]] = (JobEnded, JobCancelled, PipelineError, LlmError)


def job_id_of(state: PipelineState) -> UUID:
    job_id = state.get("job_id")
    if job_id is None:
        raise MissingJobIdError
    return UUID(job_id)


def call_context(job: JobSnapshot, stage: Stage, key: str) -> CallContext:
    return CallContext(user_id=job.user_id, job_id=job.id, stage=stage.value, call_key=f"{job.id}:{key}")


async def begin(deps: PipelineDependencies, job_id: UUID, status: JobStatus, stage: Stage) -> None:
    if await deps.store.transition(job_id, status, stage=stage.value):
        return
    snapshot = await deps.store.snapshot(job_id)
    if snapshot.status.is_terminal:
        raise JobEnded(snapshot.status)
    if snapshot.cancel_requested:
        raise JobCancelled
    raise InvalidTransitionError(f"{snapshot.status.value} cannot move to {status.value}")


async def require_reservation(deps: PipelineDependencies, job: JobSnapshot) -> None:
    if job.credits_reserved > 0 and not await deps.store.reservation_active(job.id):
        raise pipeline_error(PipelineErrorCode.RESERVATION_LOST)


async def ensure_active(deps: PipelineDependencies, job_id: UUID) -> None:
    snapshot = await deps.store.snapshot(job_id)
    if snapshot.status.is_terminal:
        raise JobEnded(snapshot.status)
    if snapshot.cancel_requested:
        raise JobCancelled


@asynccontextmanager
async def stage_scope(
    deps: PipelineDependencies, job_id: UUID, stage: Stage, *, status: JobStatus | None = None
) -> AsyncGenerator[None]:
    await begin(deps, job_id, status or STAGE_STATUS[stage], stage)
    await emit(deps, job_id, EventType.STAGE_STARTED, stage, {"stage": stage.value})
    started = deps.clock.monotonic()
    yield
    elapsed_ms = round((deps.clock.monotonic() - started) * MS_PER_SECOND)
    await emit(deps, job_id, EventType.STAGE_COMPLETED, stage, {"stage": stage.value, "durationMs": elapsed_ms})


def first_failure(failures: Sequence[BaseException]) -> BaseException:
    for kind in ERROR_PRIORITY:
        for failure in failures:
            if isinstance(failure, kind):
                return failure
    return failures[0]


async def run_bounded[ResultT](limit: int, jobs: Sequence[Callable[[], Awaitable[ResultT]]]) -> list[ResultT]:
    semaphore = asyncio.Semaphore(max(1, limit))
    failures: list[BaseException] = []

    async def guarded(job: Callable[[], Awaitable[ResultT]]) -> ResultT:
        async with semaphore:
            try:
                return await job()
            except Exception as error:
                failures.append(error)
                raise

    try:
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(guarded(job)) for job in jobs]
    except BaseExceptionGroup:
        if failures:
            raise first_failure(failures) from None
        raise
    return [task.result() for task in tasks]
