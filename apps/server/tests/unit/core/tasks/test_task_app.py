from collections.abc import AsyncIterator
from typing import ClassVar

import pytest
from procrastinate import App
from procrastinate.jobs import Status
from procrastinate.testing import InMemoryConnector
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.settings import make_settings

from motionile.core.db import run_after_commit
from motionile.core.events import DomainEvent, ProcrastinateEventDeferrer, dispatch_event, event_bus
from motionile.core.ids import new_id
from motionile.core.tasks.app import (
    DEFAULT_WORKER_QUEUES,
    RENDER_WORKER_QUEUES,
    TASK_NAMESPACE,
    Queue,
    create_task_app,
    registered_task_app,
)
from motionile.core.tasks.registry import DEFAULT_RETRY, defer_after_commit


class ScriptGenerated(DomainEvent):
    name: ClassVar[str] = "script.generated"

    script_id: str


@pytest.fixture
async def in_memory_app() -> AsyncIterator[tuple[App, InMemoryConnector]]:
    connector = InMemoryConnector()
    with registered_task_app().replace_connector(connector) as app:
        async with app.open_async():
            yield app, connector


def test_registration_is_idempotent_and_namespaced() -> None:
    first = create_task_app(make_settings())
    second = create_task_app(make_settings())

    assert first is second
    assert dispatch_event.blueprint is first
    assert dispatch_event.name == f"{TASK_NAMESPACE}:events.dispatch"
    assert dispatch_event.queue == Queue.DEFAULT.value
    assert dispatch_event.retry_strategy == DEFAULT_RETRY


def test_render_work_is_isolated_on_its_own_queue() -> None:
    assert Queue.RENDER not in DEFAULT_WORKER_QUEUES
    assert RENDER_WORKER_QUEUES == (Queue.RENDER,)


async def test_event_tasks_run_through_the_worker(in_memory_app: tuple[App, InMemoryConnector]) -> None:
    app, connector = in_memory_app
    received: list[ScriptGenerated] = []

    async def handler(event: ScriptGenerated) -> None:
        received.append(event)

    name = f"tests.on_script_generated_{new_id().hex}"
    event_bus.subscribe(ScriptGenerated, handler, name=name, run_as_task=True)

    await ProcrastinateEventDeferrer().defer(name, ScriptGenerated(script_id="s1"))
    await app.run_worker_async(wait=False, install_signal_handlers=False)

    assert received == [ScriptGenerated(script_id="s1")]
    assert [job["status"] for job in connector.jobs.values()] == [Status.SUCCEEDED.value]


async def test_failed_task_is_marked_for_retry(in_memory_app: tuple[App, InMemoryConnector]) -> None:
    app, connector = in_memory_app

    await dispatch_event.defer_async(subscription="tests.missing_subscription", payload={})
    await app.run_worker_async(wait=False, install_signal_handlers=False)

    job = next(iter(connector.jobs.values()))
    assert job["status"] == Status.TODO.value
    assert job["attempts"] == 1


async def test_defer_after_commit_enqueues_only_after_commit(in_memory_app: tuple[App, InMemoryConnector]) -> None:
    _, connector = in_memory_app
    session = AsyncSession()

    defer_after_commit(session, dispatch_event, subscription="tests.any", payload={})
    assert connector.jobs == {}

    await run_after_commit(session)
    assert len(connector.jobs) == 1
    await session.close()
