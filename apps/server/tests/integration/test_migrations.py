from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text

from motionile.core.config import PSYCOPG_SCHEME, with_driver

SERVER_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_EXTENSIONS = {"vector", "citext", "pgcrypto"}
TASK_QUEUE_TABLES = {
    "procrastinate_jobs",
    "procrastinate_events",
    "procrastinate_periodic_defers",
    "procrastinate_workers",
}


@pytest.fixture
def alembic_config(database_url: str) -> Config:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    return config


@pytest.fixture
def engine(database_url: str) -> Iterator[Engine]:
    sync_engine = create_engine(with_driver(database_url, PSYCOPG_SCHEME))
    yield sync_engine
    sync_engine.dispose()


def installed_extensions(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(connection.execute(text("SELECT extname FROM pg_extension")).scalars())


def task_queue_objects(engine: Engine) -> set[str]:
    query = text(
        "SELECT tablename FROM pg_tables WHERE tablename LIKE 'procrastinate%' "
        "UNION SELECT proname FROM pg_proc WHERE proname LIKE 'procrastinate%' "
        "UNION SELECT typname FROM pg_type WHERE typname LIKE 'procrastinate%'"
    )
    with engine.connect() as connection:
        return set(connection.execute(query).scalars())


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        exists = connection.execute(text("SELECT to_regclass('alembic_version') IS NOT NULL")).scalar_one()
        if not exists:
            return None
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()


def test_upgrade_enables_extensions_and_task_queue(alembic_config: Config, engine: Engine) -> None:
    command.upgrade(alembic_config, "head")

    assert installed_extensions(engine) >= EXPECTED_EXTENSIONS
    assert task_queue_objects(engine) >= TASK_QUEUE_TABLES
    assert current_revision(engine) == "0001"


def test_downgrade_removes_everything_and_upgrade_reapplies(alembic_config: Config, engine: Engine) -> None:
    command.upgrade(alembic_config, "head")

    command.downgrade(alembic_config, "base")

    assert not installed_extensions(engine) & EXPECTED_EXTENSIONS
    assert task_queue_objects(engine) == set()
    assert current_revision(engine) is None

    command.upgrade(alembic_config, "head")

    assert task_queue_objects(engine) >= TASK_QUEUE_TABLES
