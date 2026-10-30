from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

import structlog
from procrastinate import RetryStrategy
from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import Clock
from motionile.core.config import get_settings
from motionile.core.resources import build_resources
from motionile.core.tasks.registry import Queue, defer_after_commit, periodic_task, task
from motionile.modules.media.builders import render_events_for, render_pipeline_for, speech_for
from motionile.modules.media.composition_check import CompositionCheckService
from motionile.modules.media.pipeline import fail_stalled_renders as sweep_stalled_renders
from motionile.modules.media.render_repository import SqlRenderJobRepository

TTS_CACHE_RETENTION = timedelta(days=90)
RENDER_RUN_TASK = "render.run"
CHECK_COMPOSITION_TASK = "media.check_composition"
RENDER_RETRY = RetryStrategy(max_attempts=3, wait=5)
CHECK_PRIORITY = 10
CHECK_RETRY = RetryStrategy(max_attempts=3, wait=5)

logger = structlog.get_logger(__name__)


class CachePruner(Protocol):
    async def prune_cache(self, older_than: datetime) -> int: ...


async def prune_unused_tts_cache(speech: CachePruner, clock: Clock) -> int:
    pruned = await speech.prune_cache(clock.now() - TTS_CACHE_RETENTION)
    logger.info("media.tts_cache_pruned", entries=pruned)
    return pruned


@task(name=RENDER_RUN_TASK, queue=Queue.RENDER, retry=RENDER_RETRY)
async def run_render(render_id: str) -> None:
    from motionile.modules.media.pipeline.toolchain import build_toolchain  # noqa: PLC0415

    settings = get_settings()
    resources = build_resources(settings, application_name="motionile-render")
    try:
        pipeline = render_pipeline_for(resources, lambda fps: build_toolchain(settings, fps))
        await pipeline.run(UUID(render_id))
    finally:
        await resources.aclose()


@task(name=CHECK_COMPOSITION_TASK, queue=Queue.RENDER, retry=CHECK_RETRY)
async def check_composition(job_id: str, check_id: str) -> None:
    from motionile.modules.media.check_browser import check_browser_opener  # noqa: PLC0415

    settings = get_settings()
    resources = build_resources(settings, application_name="motionile-render-check")
    try:
        service = CompositionCheckService(
            resources.storage,
            check_browser_opener(settings),
            timeout_seconds=float(settings.render.stage_timeout_seconds),
        )
        await service.run(UUID(job_id), check_id)
    finally:
        await resources.aclose()


async def defer_composition_check(job_id: UUID, check_id: str) -> None:
    try:
        await check_composition.configure(queueing_lock=check_id, priority=CHECK_PRIORITY).defer_async(
            job_id=str(job_id), check_id=check_id
        )
    except AlreadyEnqueued:
        logger.info("media.composition_check_already_queued", job_id=str(job_id))


def dispatch_render(session: AsyncSession, render_id: UUID) -> None:
    defer_after_commit(session, run_render, render_id=str(render_id))


@periodic_task(name="media.prune_tts_cache", queue=Queue.DEFAULT, cron="30 3 * * *")
async def prune_tts_cache() -> None:
    resources = build_resources(get_settings(), application_name="motionile-media-prune")
    try:
        await prune_unused_tts_cache(speech_for(resources), resources.clock)
    finally:
        await resources.aclose()


@periodic_task(name="media.fail_stalled_renders", queue=Queue.DEFAULT, cron="*/5 * * * *")
async def fail_stalled_renders() -> None:
    settings = get_settings()
    resources = build_resources(settings, application_name="motionile-media-sweeper")
    try:
        await sweep_stalled_renders(
            resources.database.transaction,
            SqlRenderJobRepository,
            render_events_for(resources),
            resources.clock,
            settings.render.stall_seconds,
        )
    finally:
        await resources.aclose()
