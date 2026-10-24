from collections.abc import Iterator

import pytest
from langgraph.checkpoint.postgres.base import BasePostgresSaver
from sqlalchemy import Connection, create_engine, text

from motionile.core.config import PSYCOPG_SCHEME, with_driver

CHECKPOINT_TABLES = {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"}
CHECKPOINT_WRITES_COLUMNS = {
    "thread_id",
    "checkpoint_ns",
    "checkpoint_id",
    "task_id",
    "idx",
    "channel",
    "type",
    "blob",
    "task_path",
}


@pytest.fixture
def connection(migrated_database_url: str) -> Iterator[Connection]:
    engine = create_engine(with_driver(migrated_database_url, PSYCOPG_SCHEME))
    with engine.connect() as opened:
        yield opened
    engine.dispose()


def test_the_checkpointer_tables_live_in_the_langgraph_schema(connection: Connection) -> None:
    query = text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'langgraph'")

    assert set(connection.execute(query).scalars()) == CHECKPOINT_TABLES


def test_the_checkpointer_tables_are_not_created_in_public(connection: Connection) -> None:
    query = text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")

    assert not CHECKPOINT_TABLES & set(connection.execute(query).scalars())


def test_every_library_migration_is_recorded_as_applied(connection: Connection) -> None:
    recorded = list(connection.execute(text("SELECT v FROM langgraph.checkpoint_migrations ORDER BY v")).scalars())

    assert recorded == list(range(len(BasePostgresSaver.MIGRATIONS)))


def test_the_checkpoint_writes_table_has_the_columns_the_library_writes(connection: Connection) -> None:
    query = text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'langgraph' AND table_name = 'checkpoint_writes'"
    )

    assert set(connection.execute(query).scalars()) == CHECKPOINT_WRITES_COLUMNS


def test_the_thread_indexes_exist(connection: Connection) -> None:
    query = text("SELECT indexname FROM pg_indexes WHERE schemaname = 'langgraph'")

    assert {
        "checkpoints_thread_id_idx",
        "checkpoint_blobs_thread_id_idx",
        "checkpoint_writes_thread_id_idx",
    } <= set(connection.execute(query).scalars())
