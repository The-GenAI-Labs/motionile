import functools
import importlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from procrastinate import App, PsycopgConnector
from psycopg_pool import AsyncConnectionPool

from motionile.core.config import Settings
from motionile.core.tasks.registry import DEFAULT_RETRY, TASK_MODULES, Queue, blueprint

TASK_NAMESPACE = "motionile"
DEFAULT_WORKER_QUEUES = (Queue.DEFAULT, Queue.BILLING, Queue.PUBLISHING)
RENDER_WORKER_QUEUES = (Queue.RENDER,)

__all__ = [
    "DEFAULT_RETRY",
    "DEFAULT_WORKER_QUEUES",
    "RENDER_WORKER_QUEUES",
    "TASK_NAMESPACE",
    "Queue",
    "create_task_app",
    "load_task_modules",
    "open_for_deferring",
    "registered_task_app",
]


def load_task_modules() -> None:
    for module in TASK_MODULES:
        importlib.import_module(module)


@functools.cache
def registered_task_app() -> App:
    load_task_modules()
    app = App(connector=PsycopgConnector())
    app.add_tasks_from(blueprint, namespace=TASK_NAMESPACE)
    return app


def create_task_app(settings: Settings) -> App:
    app = registered_task_app()
    connector = PsycopgConnector(conninfo=settings.database.migration_url)
    app.connector = connector
    app.job_manager.connector = connector
    return app


@asynccontextmanager
async def open_for_deferring(app: App, settings: Settings) -> AsyncGenerator[App]:
    pool = AsyncConnectionPool(
        settings.database.migration_url,
        open=False,
        min_size=1,
        max_size=4,
        check=AsyncConnectionPool.check_connection,
    )
    await pool.open(wait=False)
    try:
        async with app.open_async(pool=pool):
            yield app
    finally:
        await pool.close()
