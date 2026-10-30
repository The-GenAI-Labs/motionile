from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import pytest
from langchain_core.runnables.config import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver, empty_checkpoint
from langgraph.checkpoint.memory import InMemorySaver
from tests.fakes.generation import FakeCheckpoints
from tests.fakes.settings import make_settings
from tests.fakes.storage import InMemoryStorage
from tests.unit.modules.generation.support import Harness

from motionile.core.config import Settings
from motionile.core.ids import new_id
from motionile.modules.generation import JobNotDeletableError
from motionile.modules.generation.checkpoints import PostgresCheckpointPurger
from motionile.modules.generation.hooks import HOOK_NAME, purge_jobs
from motionile.modules.media import job_work_prefix
from motionile.modules.users import purge_registry


async def chunks(data: bytes) -> AsyncIterator[bytes]:
    yield data


async def put_thread(saver: InMemorySaver, job_id: UUID) -> None:
    config = RunnableConfig(configurable={"thread_id": str(job_id), "checkpoint_ns": ""})
    await saver.aput(config, empty_checkpoint(), {"source": "input", "step": 0, "parents": {}}, {})


async def thread_exists(saver: InMemorySaver, job_id: UUID) -> bool:
    config = RunnableConfig(configurable={"thread_id": str(job_id), "checkpoint_ns": ""})
    return await saver.aget_tuple(config) is not None


class FakeJobIds:
    def __init__(self, ids: dict[UUID, list[UUID]]) -> None:
        self._ids = ids

    async def ids_of(self, user_id: UUID) -> list[UUID]:
        return self._ids.get(user_id, [])


async def test_the_purger_deletes_the_threads_of_the_given_jobs_only() -> None:
    saver = InMemorySaver()
    doomed, other = new_id(), new_id()
    for job_id in (doomed, other):
        await put_thread(saver, job_id)
    opened: list[Settings] = []

    @asynccontextmanager
    async def source(settings: Settings) -> AsyncGenerator[BaseCheckpointSaver[Any]]:
        opened.append(settings)
        yield saver

    settings = make_settings()
    await PostgresCheckpointPurger(settings, source).purge([doomed])

    assert opened == [settings]
    assert not await thread_exists(saver, doomed)
    assert await thread_exists(saver, other)


async def test_the_purger_opens_no_connection_without_jobs() -> None:
    opened: list[Settings] = []

    @asynccontextmanager
    async def source(settings: Settings) -> AsyncGenerator[BaseCheckpointSaver[Any]]:
        opened.append(settings)
        yield InMemorySaver()

    await PostgresCheckpointPurger(make_settings(), source).purge([])

    assert opened == []


async def test_deleting_a_job_deletes_its_checkpoint_thread(harness: Harness) -> None:
    job = harness.world.add_job(harness.user_id, status="failed", error_code="tts_failed")
    other = harness.world.add_job(harness.user_id, status="failed", error_code="tts_failed")

    await harness.service.delete(harness.session, harness.user_id, job.id)

    assert harness.checkpoints.purged == [job.id]
    assert other.id in harness.world.jobs


async def test_a_job_that_cannot_be_deleted_keeps_its_checkpoints(harness: Harness) -> None:
    job = harness.world.add_job(harness.user_id, status="voicing")

    with pytest.raises(JobNotDeletableError):
        await harness.service.delete(harness.session, harness.user_id, job.id)

    assert harness.checkpoints.purged == []


async def test_the_user_purge_deletes_checkpoints_and_work_files_of_every_job_of_that_user() -> None:
    user, other_user = new_id(), new_id()
    owned = [new_id(), new_id()]
    foreign = new_id()
    storage = InMemoryStorage()
    for job_id in (*owned, foreign):
        await storage.put(f"{job_work_prefix(job_id)}checks/abc/request.json", chunks(b"{}"), content_type="text/plain")
    checkpoints = FakeCheckpoints()

    await purge_jobs(user, FakeJobIds({user: owned, other_user: [foreign]}), checkpoints, storage)

    assert checkpoints.purged == owned
    for job_id in owned:
        assert not await storage.exists(f"{job_work_prefix(job_id)}checks/abc/request.json")
    assert await storage.exists(f"{job_work_prefix(foreign)}checks/abc/request.json")


async def test_a_failing_checkpoint_purge_stops_the_user_purge_before_any_file_is_removed() -> None:
    user, job_id = new_id(), new_id()
    storage = InMemoryStorage()
    await storage.put(f"{job_work_prefix(job_id)}checks/abc/request.json", chunks(b"{}"), content_type="text/plain")
    checkpoints = FakeCheckpoints()
    checkpoints.failure = ConnectionError("database down")

    with pytest.raises(ConnectionError):
        await purge_jobs(user, FakeJobIds({user: [job_id]}), checkpoints, storage)

    assert await storage.exists(f"{job_work_prefix(job_id)}checks/abc/request.json")


async def test_a_user_without_jobs_purges_nothing() -> None:
    checkpoints = FakeCheckpoints()

    await purge_jobs(new_id(), FakeJobIds({}), checkpoints, InMemoryStorage())

    assert checkpoints.purged == []


def test_the_generation_purge_hook_registers_when_the_package_loads() -> None:
    assert HOOK_NAME in purge_registry.names()


def test_the_job_work_prefix_is_the_private_work_folder_of_the_job() -> None:
    job_id = new_id()

    assert job_work_prefix(job_id) == f"work/jobs/{job_id}/"
    assert job_work_prefix(job_id).startswith("work/")
