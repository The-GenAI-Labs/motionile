from collections.abc import AsyncIterator, Iterator
from uuid import UUID

import pytest
from procrastinate import App
from procrastinate.testing import InMemoryConnector
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.settings import make_settings

from motionile.core.db import run_after_commit
from motionile.core.ids import new_id
from motionile.core.tasks.app import registered_task_app
from motionile.core.tasks.registry import TASK_MODULES, Queue
from motionile.modules.generation import PipelineNotWiredError, ResumeKind, install_runner, runner_for
from motionile.modules.generation import tasks as generation_tasks
from motionile.modules.generation.runner import registry


class RecordingRunner:
    def __init__(self) -> None:
        self.runs: list[UUID] = []
        self.resumes: list[tuple[UUID, ResumeKind, str | None]] = []

    async def run(self, job_id: UUID) -> None:
        self.runs.append(job_id)

    async def resume(self, job_id: UUID, kind: ResumeKind, instructions: str | None) -> None:
        self.resumes.append((job_id, kind, instructions))


@pytest.fixture
async def in_memory_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[App, InMemoryConnector]]:
    connector = InMemoryConnector()
    with registered_task_app().replace_connector(connector) as app:
        monkeypatch.setattr(app, "periodic_defaults", {"max_delay": -1})
        async with app.open_async():
            yield app, connector


@pytest.fixture(autouse=True)
def clean_registry() -> Iterator[None]:
    registry.clear()
    yield
    registry.clear()


def test_an_unwired_pipeline_fails_loudly() -> None:
    with pytest.raises(PipelineNotWiredError, match="the pipeline runner is not wired"):
        runner_for(make_settings())


def test_an_installed_runner_is_returned() -> None:
    runner = RecordingRunner()
    install_runner(runner)

    assert runner_for(make_settings()) is runner


async def test_the_worker_hands_a_run_to_the_runner(in_memory_app: tuple[App, InMemoryConnector]) -> None:
    app, _ = in_memory_app
    runner = RecordingRunner()
    install_runner(runner)
    session = AsyncSession()
    job_id = new_id()

    generation_tasks.DISPATCH.run(session, job_id)
    await run_after_commit(session)
    await app.run_worker_async(wait=False, install_signal_handlers=False, queues=[Queue.GENERATION.value])

    assert runner.runs == [job_id]
    await session.close()


async def test_the_worker_passes_the_kind_and_the_instructions_to_the_runner(
    in_memory_app: tuple[App, InMemoryConnector],
) -> None:
    app, _ = in_memory_app
    runner = RecordingRunner()
    install_runner(runner)
    session = AsyncSession()
    job_id = new_id()

    generation_tasks.DISPATCH.resume(session, job_id, ResumeKind.REGENERATE, "shorter")
    await run_after_commit(session)
    await app.run_worker_async(wait=False, install_signal_handlers=False, queues=[Queue.GENERATION.value])

    assert runner.resumes == [(job_id, ResumeKind.REGENERATE, "shorter")]
    await session.close()


def test_the_task_module_is_listed_for_the_worker() -> None:
    assert "motionile.modules.generation.tasks" in TASK_MODULES


async def test_dispatching_defers_with_the_job_lock_after_commit(
    in_memory_app: tuple[App, InMemoryConnector],
) -> None:
    _, connector = in_memory_app
    session = AsyncSession()
    job_id = new_id()

    generation_tasks.DISPATCH.run(session, job_id)
    generation_tasks.DISPATCH.resume(session, job_id, ResumeKind.APPROVE, None)
    assert connector.jobs == {}
    await run_after_commit(session)

    jobs = sorted(connector.jobs.values(), key=lambda job: str(job["task_name"]))
    assert [job["lock"] for job in jobs] == [str(job_id), str(job_id)]
    assert [job["args"] for job in jobs] == [
        {"job_id": str(job_id), "kind": "approve", "instructions": None},
        {"job_id": str(job_id)},
    ]
    assert {job["queue_name"] for job in jobs} == {Queue.GENERATION.value}
    await session.close()
