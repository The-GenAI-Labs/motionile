from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.resources import Resources
from motionile.core.storage.base import Storage
from motionile.modules.generation.checkpoints import PostgresCheckpointPurger
from motionile.modules.generation.ports import CheckpointPurger
from motionile.modules.generation.repository import SqlJobRepository
from motionile.modules.media import job_work_prefix
from motionile.modules.users import purge_registry

HOOK_NAME = "generation"


class JobIds(Protocol):
    async def ids_of(self, user_id: UUID) -> list[UUID]: ...


async def purge_jobs(user_id: UUID, jobs: JobIds, checkpoints: CheckpointPurger, storage: Storage) -> None:
    job_ids = await jobs.ids_of(user_id)
    await checkpoints.purge(job_ids)
    for job_id in job_ids:
        await storage.delete_prefix(job_work_prefix(job_id))


async def purge_user_jobs(resources: Resources, session: AsyncSession, user_id: UUID) -> None:
    await purge_jobs(
        user_id, SqlJobRepository(session), PostgresCheckpointPurger(resources.settings), resources.storage
    )


def register_hooks() -> None:
    purge_registry.register(HOOK_NAME, purge_user_jobs)
