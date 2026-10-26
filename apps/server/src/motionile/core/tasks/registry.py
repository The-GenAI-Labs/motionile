import functools
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import cast

import structlog
from procrastinate import Blueprint, JobContext, RetryStrategy
from procrastinate.tasks import Task
from procrastinate.types import JSONValue
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.db import after_commit

TASK_MODULES: tuple[str, ...] = (
    "motionile.core.events",
    "motionile.modules.billing.tasks",
    "motionile.modules.catalog.tasks",
    "motionile.modules.credits.tasks",
    "motionile.modules.generation.tasks",
    "motionile.modules.media.tasks",
    "motionile.modules.notifications.tasks",
    "motionile.modules.prompts.tasks",
    "motionile.modules.users.tasks",
    "motionile.modules.voices.tasks",
)

logger = structlog.get_logger(__name__)
blueprint = Blueprint()


class Queue(StrEnum):
    DEFAULT = "default"
    BILLING = "billing"
    PUBLISHING = "publishing"
    GENERATION = "generation"
    RENDER = "render"


DEFAULT_RETRY = RetryStrategy(max_attempts=5, wait=2, exponential_wait=2)

type TaskBody = Callable[..., Awaitable[None]]
type ScheduledBody = Callable[[], Awaitable[None]]
type RegisteredTask = Task[..., Awaitable[None], ...]


def task(
    *,
    name: str,
    queue: Queue,
    retry: RetryStrategy | int | bool = DEFAULT_RETRY,
) -> Callable[[TaskBody], RegisteredTask]:
    def register(body: TaskBody) -> RegisteredTask:
        @functools.wraps(body)
        async def run_with_context(context: JobContext, **kwargs: object) -> None:
            job = context.job
            with structlog.contextvars.bound_contextvars(
                task=name, task_job_id=job.id, attempt=job.attempts + 1, queue=queue.value
            ):
                logger.info("task.started")
                try:
                    await body(**kwargs)
                except Exception:
                    logger.exception("task.failed")
                    raise
                logger.info("task.succeeded")

        return blueprint.task(name=name, queue=queue.value, retry=retry, pass_context=True)(run_with_context)

    return register


def periodic_task(
    *,
    name: str,
    queue: Queue,
    cron: str,
    retry: RetryStrategy | int | bool = DEFAULT_RETRY,
) -> Callable[[ScheduledBody], RegisteredTask]:
    def register(body: ScheduledBody) -> RegisteredTask:
        async def run_scheduled(**_: object) -> None:
            await body()

        registered = task(name=name, queue=queue, retry=retry)(run_scheduled)
        return cast(
            "RegisteredTask", blueprint.periodic(cron=cron)(cast("Task[..., Awaitable[None], [int]]", registered))
        )

    return register


def defer_after_commit(
    session: AsyncSession,
    registered: RegisteredTask,
    *,
    priority: int = 0,
    lock: str | None = None,
    **arguments: JSONValue,
) -> None:
    async def enqueue() -> None:
        await registered.configure(priority=priority, lock=lock).defer_async(**arguments)

    after_commit(session, enqueue)
