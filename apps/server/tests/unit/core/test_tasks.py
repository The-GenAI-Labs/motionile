from procrastinate import App, PsycopgConnector

from motionile.core.config import Settings
from motionile.core.tasks.app import DEFAULT_WORKER_QUEUES, RENDER_WORKER_QUEUES, Queue, create_task_app


def test_defines_the_four_queues() -> None:
    assert {queue.value for queue in Queue} == {"default", "billing", "publishing", "render"}


def test_workers_split_queues_without_overlap() -> None:
    assert set(DEFAULT_WORKER_QUEUES) | set(RENDER_WORKER_QUEUES) == set(Queue)
    assert not set(DEFAULT_WORKER_QUEUES) & set(RENDER_WORKER_QUEUES)


def test_task_app_uses_a_psycopg_connector() -> None:
    app = create_task_app(Settings())

    assert isinstance(app, App)
    assert isinstance(app.connector, PsycopgConnector)
