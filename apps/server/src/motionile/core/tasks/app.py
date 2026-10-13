from enum import StrEnum

from procrastinate import App, PsycopgConnector

from motionile.core.config import Settings


class Queue(StrEnum):
    DEFAULT = "default"
    BILLING = "billing"
    PUBLISHING = "publishing"
    RENDER = "render"


DEFAULT_WORKER_QUEUES = (Queue.DEFAULT, Queue.BILLING, Queue.PUBLISHING)
RENDER_WORKER_QUEUES = (Queue.RENDER,)


def create_task_app(settings: Settings) -> App:
    connector = PsycopgConnector(conninfo=settings.migration_database_url)
    return App(connector=connector)
