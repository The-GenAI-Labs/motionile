from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Final, cast
from uuid import UUID

import structlog
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row

from motionile.core.config import Settings
from motionile.core.resources import Resources, build_resources
from motionile.engine.ai.graphs.deps import PipelineDependencies
from motionile.engine.ai.graphs.resume import ApprovalResume
from motionile.engine.ai.graphs.run import RunOutcome, run_graph
from motionile.modules.generation.pipeline_deps import build_dependencies
from motionile.modules.generation.ports import ResumeKind

CHECKPOINT_SCHEMA: Final = "langgraph"
APPLICATION_NAME: Final = "motionile-generation"

type ResourceSource = Callable[[], AbstractAsyncContextManager[Resources]]
type CheckpointSource = Callable[[Settings], AbstractAsyncContextManager[BaseCheckpointSaver[Any]]]
type DependencyBuilder = Callable[[Resources, UUID], Awaitable[PipelineDependencies]]

logger = structlog.get_logger(__name__)


def worker_resources(settings: Settings) -> ResourceSource:
    @asynccontextmanager
    async def open_resources() -> AsyncGenerator[Resources]:
        resources = build_resources(settings, application_name=APPLICATION_NAME)
        try:
            yield resources
        finally:
            await resources.aclose()

    return open_resources


@asynccontextmanager
async def postgres_checkpointer(settings: Settings) -> AsyncGenerator[BaseCheckpointSaver[Any]]:
    options: dict[str, Any] = {
        "autocommit": True,
        "prepare_threshold": 0,
        "row_factory": dict_row,
        "options": f"-c search_path={CHECKPOINT_SCHEMA}",
    }
    connection = cast(
        "AsyncConnection[DictRow]", await AsyncConnection.connect(settings.database.migration_url, **options)
    )
    async with connection:
        yield AsyncPostgresSaver(connection)


class GraphPipelineRunner:
    def __init__(
        self,
        open_resources: ResourceSource,
        open_checkpointer: CheckpointSource = postgres_checkpointer,
        build: DependencyBuilder = build_dependencies,
    ) -> None:
        self._open_resources = open_resources
        self._open_checkpointer = open_checkpointer
        self._build = build

    async def run(self, job_id: UUID) -> None:
        await self._execute(job_id, None)

    async def resume(self, job_id: UUID, kind: ResumeKind, instructions: str | None) -> None:
        if kind is ResumeKind.APPROVE:
            await self._execute(job_id, ApprovalResume.approve())
            return
        await self._execute(job_id, ApprovalResume.regenerate(instructions))

    async def _execute(self, job_id: UUID, resume: ApprovalResume | None) -> RunOutcome:
        async with self._open_resources() as resources, self._open_checkpointer(resources.settings) as saver:
            deps = await self._build(resources, job_id)
            outcome = await run_graph(deps, job_id, saver, resume)
        logger.info("generation.run_finished", job_id=str(job_id), outcome=outcome.value, resumed=resume is not None)
        return outcome


def build_runner(settings: Settings) -> GraphPipelineRunner:
    return GraphPipelineRunner(worker_resources(settings))
