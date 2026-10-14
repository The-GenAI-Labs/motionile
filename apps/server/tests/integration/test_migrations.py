from collections.abc import Iterator

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import DBAPIError
from tests.integration.conftest import alembic_config_for

from motionile.core.config import PSYCOPG_SCHEME, with_driver
from motionile.models import metadata

EXPECTED_EXTENSIONS = {"vector", "citext", "pgcrypto"}
TASK_QUEUE_TABLES = {
    "procrastinate_jobs",
    "procrastinate_events",
    "procrastinate_periodic_defers",
    "procrastinate_workers",
}
APPLICATION_TABLES = {"audit_log", "idempotency_records"}
HEAD_REVISION = "0002"


@pytest.fixture
def engine(scratch_database_url: str) -> Iterator[Engine]:
    sync_engine = create_engine(with_driver(scratch_database_url, PSYCOPG_SCHEME))
    command.downgrade(alembic_config_for(scratch_database_url), "base")
    yield sync_engine
    sync_engine.dispose()


@pytest.fixture
def migrated_engine(migrated_database_url: str) -> Iterator[Engine]:
    sync_engine = create_engine(with_driver(migrated_database_url, PSYCOPG_SCHEME))
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


def application_tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names()) & APPLICATION_TABLES


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        exists = connection.execute(text("SELECT to_regclass('alembic_version') IS NOT NULL")).scalar_one()
        if not exists:
            return None
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()


def constraint_names(engine: Engine, table: str) -> set[str]:
    query = text("SELECT conname FROM pg_constraint WHERE conrelid = CAST(:table AS regclass)")
    with engine.connect() as connection:
        return set(connection.execute(query, {"table": table}).scalars())


def only_application_tables(name: str | None, kind: str, _: object) -> bool:
    return kind != "table" or name in APPLICATION_TABLES


def schema_drift(engine: Engine) -> list[object]:
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"compare_type": True, "include_name": only_application_tables},
        )
        return list(compare_metadata(context, metadata))


def test_upgrade_creates_everything(scratch_database_url: str, engine: Engine) -> None:
    command.upgrade(alembic_config_for(scratch_database_url), "head")

    assert installed_extensions(engine) >= EXPECTED_EXTENSIONS
    assert task_queue_objects(engine) >= TASK_QUEUE_TABLES
    assert application_tables(engine) == APPLICATION_TABLES
    assert current_revision(engine) == HEAD_REVISION


def test_models_match_the_migrated_schema(scratch_database_url: str, engine: Engine) -> None:
    command.upgrade(alembic_config_for(scratch_database_url), "head")

    assert schema_drift(engine) == []
    assert constraint_names(engine, "idempotency_records") == {
        "pk_idempotency_records",
        "uq_idempotency_records_scope_user_id_key",
        "ck_idempotency_records_status",
        "ck_idempotency_records_scope_length",
        "ck_idempotency_records_key_format",
        "ck_idempotency_records_request_hash_length",
        "ck_idempotency_records_response_status_range",
        "ck_idempotency_records_completed_has_response",
        "ck_idempotency_records_in_progress_has_lock",
    }
    assert "ck_audit_log_action_format" in constraint_names(engine, "audit_log")


def test_each_revision_downgrades_and_reapplies(scratch_database_url: str, engine: Engine) -> None:
    config = alembic_config_for(scratch_database_url)
    command.upgrade(config, "head")

    command.downgrade(config, "0001")
    assert application_tables(engine) == set()
    assert current_revision(engine) == "0001"

    command.downgrade(config, "base")
    assert not installed_extensions(engine) & EXPECTED_EXTENSIONS
    assert task_queue_objects(engine) == set()
    assert current_revision(engine) is None

    command.upgrade(config, "head")
    assert application_tables(engine) == APPLICATION_TABLES
    assert schema_drift(engine) == []


def insert_audit_row(engine: Engine) -> str:
    with engine.begin() as connection:
        return str(
            connection.execute(
                text(
                    "INSERT INTO audit_log (id, actor_type, action) "
                    "VALUES (gen_random_uuid(), 'system', 'tests.row.created') RETURNING id"
                )
            ).scalar_one()
        )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_log SET action = 'tests.row.changed' WHERE id = :id",
        "DELETE FROM audit_log WHERE id = :id",
    ],
)
def test_audit_log_is_append_only(migrated_engine: Engine, statement: str) -> None:
    row_id = insert_audit_row(migrated_engine)

    with pytest.raises(DBAPIError, match="append-only"), migrated_engine.begin() as connection:
        connection.execute(text(statement), {"id": row_id})


def test_audit_log_allows_explicit_retention_purge(migrated_engine: Engine) -> None:
    row_id = insert_audit_row(migrated_engine)

    with migrated_engine.begin() as connection:
        connection.execute(text("SET LOCAL motionile.allow_purge = 'on'"))
        deleted = connection.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": row_id}).rowcount

    assert deleted == 1


@pytest.mark.parametrize(("actor_type", "action"), [("robot", "tests.row.created"), ("system", "NotDotted")])
def test_audit_log_check_constraints(migrated_engine: Engine, actor_type: str, action: str) -> None:
    statement = text("INSERT INTO audit_log (id, actor_type, action) VALUES (gen_random_uuid(), :actor_type, :action)")
    with pytest.raises(DBAPIError, match="ck_audit_log"), migrated_engine.begin() as connection:
        connection.execute(statement, {"actor_type": actor_type, "action": action})
