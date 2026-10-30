from collections.abc import AsyncGenerator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Final, cast
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row

from motionile.core.config import Settings

CHECKPOINT_SCHEMA: Final = "langgraph"

type CheckpointSource = Callable[[Settings], AbstractAsyncContextManager[BaseCheckpointSaver[Any]]]


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


class PostgresCheckpointPurger:
    def __init__(self, settings: Settings, open_checkpointer: CheckpointSource = postgres_checkpointer) -> None:
        self._settings = settings
        self._open_checkpointer = open_checkpointer

    async def purge(self, job_ids: Sequence[UUID]) -> None:
        if not job_ids:
            return
        async with self._open_checkpointer(self._settings) as saver:
            for job_id in job_ids:
                await saver.adelete_thread(str(job_id))
