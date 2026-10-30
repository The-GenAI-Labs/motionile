from collections.abc import Awaitable, Callable
from uuid import UUID

import structlog
from procrastinate import RetryStrategy
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.config import get_settings
from motionile.core.resources import build_resources
from motionile.core.tasks.registry import Queue, defer_after_commit, periodic_task, task
from motionile.modules.generation.ports import JobDispatch, ResumeKind
from motionile.modules.generation.runner import runner_for
from motionile.modules.generation.sweepers import Sweeper

RUN_JOB_TASK = "generation.run_job"
RESUME_JOB_TASK = "generation.resume_job"
GENERATION_RETRY = RetryStrategy(max_attempts=5, wait=20, exponential_wait=3)

logger = structlog.get_logger(__name__)


@task(name=RUN_JOB_TASK, queue=Queue.GENERATION, retry=GENERATION_RETRY)
async def run_job(job_id: str) -> None:
    await runner_for(get_settings()).run(UUID(job_id))


@task(name=RESUME_JOB_TASK, queue=Queue.GENERATION, retry=GENERATION_RETRY)
async def resume_job(job_id: str, kind: str, instructions: str | None = None) -> None:
    await runner_for(get_settings()).resume(UUID(job_id), ResumeKind(kind), instructions)


def dispatch_run(session: AsyncSession, job_id: UUID) -> None:
    defer_after_commit(session, run_job, lock=str(job_id), job_id=str(job_id))


def dispatch_resume(session: AsyncSession, job_id: UUID, kind: ResumeKind, instructions: str | None) -> None:
    defer_after_commit(
        session, resume_job, lock=str(job_id), job_id=str(job_id), kind=kind.value, instructions=instructions
    )


DISPATCH = JobDispatch(run=dispatch_run, resume=dispatch_resume)


async def sweep(name: str, run: Callable[[Sweeper], Awaitable[int]]) -> None:
    from motionile.modules.generation.sweeper_wiring import sweeper_for  # noqa: PLC0415

    resources = build_resources(get_settings(), application_name="motionile-generation-sweeper")
    try:
        handled = await run(sweeper_for(resources))
        logger.info("generation.sweep_finished", sweep=name, handled=handled)
    finally:
        await resources.aclose()


@periodic_task(name="generation.fail_stalled_jobs", queue=Queue.GENERATION, cron="*/5 * * * *")
async def fail_stalled_jobs() -> None:
    await sweep("fail_stalled_jobs", lambda sweeper: sweeper.fail_stalled_jobs())


@periodic_task(name="generation.cancel_expired_approvals", queue=Queue.GENERATION, cron="*/15 * * * *")
async def cancel_expired_approvals() -> None:
    await sweep("cancel_expired_approvals", lambda sweeper: sweeper.cancel_expired_approvals())


@periodic_task(name="generation.finalize_cancelled_jobs", queue=Queue.GENERATION, cron="*/2 * * * *")
async def finalize_cancelled_jobs() -> None:
    await sweep("finalize_cancelled_jobs", lambda sweeper: sweeper.finalize_cancelled_jobs())
