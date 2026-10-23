from datetime import timedelta
from uuid import UUID

import structlog
from procrastinate import RetryStrategy
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.config import get_settings
from motionile.core.resources import build_resources
from motionile.core.tasks.registry import Queue, defer_after_commit, periodic_task, task
from motionile.modules.voices.domain import (
    CLONE_MAX_ATTEMPTS,
    CLONE_RETRY_EXPONENTIAL_WAIT,
    CLONE_RETRY_WAIT_SECONDS,
    STALLED_CLONE_AGE,
)
from motionile.modules.voices.factory import build_clone_runner, build_maintenance
from motionile.modules.voices.runner import RETRYABLE_ERRORS

ABANDONED_SAMPLE_AGE = timedelta(hours=3)
CLONE_RETRY = RetryStrategy(
    max_attempts=CLONE_MAX_ATTEMPTS,
    wait=CLONE_RETRY_WAIT_SECONDS,
    exponential_wait=CLONE_RETRY_EXPONENTIAL_WAIT,
    retry_exceptions=RETRYABLE_ERRORS,
)

logger = structlog.get_logger(__name__)


@task(name="voices.clone", queue=Queue.DEFAULT, retry=CLONE_RETRY)
async def clone_voice(voice_id: str, reservation_id: str | None = None) -> None:
    resources = build_resources(get_settings(), application_name="motionile-voices-clone")
    try:
        await build_clone_runner(resources).run(UUID(voice_id), UUID(reservation_id) if reservation_id else None)
    finally:
        await resources.aclose()


def defer_clone(session: AsyncSession, voice_id: UUID, reservation_id: UUID | None) -> None:
    defer_after_commit(
        session,
        clone_voice,
        voice_id=str(voice_id),
        reservation_id=str(reservation_id) if reservation_id is not None else None,
    )


@periodic_task(name="voices.sweep", queue=Queue.DEFAULT, cron="17 * * * *")
async def sweep_voices() -> None:
    resources = build_resources(get_settings(), application_name="motionile-voices-sweep")
    try:
        maintenance = build_maintenance(resources)
        stalled = await maintenance.fail_stalled_clones(STALLED_CLONE_AGE)
        removed = await maintenance.purge_abandoned_samples(ABANDONED_SAMPLE_AGE)
        logger.info("voices.swept", stalled_clones=stalled, abandoned_files=removed)
    finally:
        await resources.aclose()
