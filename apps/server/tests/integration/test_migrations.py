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
EARLIER_TABLES = {
    "audit_log",
    "idempotency_records",
    "users",
    "user_contacts",
    "roles",
    "user_roles",
    "credentials",
    "oauth_identities",
    "sessions",
    "permissions",
    "role_permissions",
    "user_preferences",
    "system_settings",
    "feature_flags",
    "categories",
    "topics",
    "catalog_slug_history",
}
BILLING_TABLES = {
    "products",
    "billing_customers",
    "subscriptions",
    "orders",
    "payments",
    "refunds",
    "webhook_events",
    "billing_reconciliation_runs",
    "credit_wallets",
    "credit_lots",
    "credit_reservations",
    "credit_ledger",
    "usage_records",
}
MEDIA_TABLES = {
    "assets",
    "renders",
    "renditions",
    "tts_cache",
    "music_tracks",
    "voices",
    "voice_consents",
}
MEDIA_PERMISSIONS = {"render.testbed", "voices.manage", "music.manage"}
GENERATION_TABLES = {
    "jobs",
    "storyboards",
    "scenes",
    "job_events",
    "share_links",
    "prompt_templates",
    "prompt_versions",
    "eval_runs",
    "skills",
    "skill_versions",
    "skill_files",
    "skill_embeddings",
}
GENERATION_PERMISSIONS = {"prompts.manage", "skills.manage", "jobs.read_all", "evals.run"}
CHECKPOINT_TABLES = {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"}
APPLICATION_TABLES = EARLIER_TABLES | BILLING_TABLES | MEDIA_TABLES | GENERATION_TABLES
HEAD_REVISION = "0007"


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
        "fk_idempotency_records_user_id_users",
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


def database_functions(engine: Engine) -> set[str]:
    query = text("SELECT proname FROM pg_proc WHERE proname LIKE 'forbid_%'")
    with engine.connect() as connection:
        return set(connection.execute(query).scalars())


def billing_permissions(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(connection.execute(text("SELECT key FROM permissions WHERE key LIKE 'billing.%'")).scalars())


def test_billing_revision_downgrades_cleanly_and_reapplies(scratch_database_url: str, engine: Engine) -> None:
    config = alembic_config_for(scratch_database_url)
    command.upgrade(config, "head")
    assert len(billing_permissions(engine)) == 5
    assert database_functions(engine) == {"forbid_append_only_mutation", "forbid_used_product_financial_change"}

    command.downgrade(config, "0004")

    assert current_revision(engine) == "0004"
    assert application_tables(engine) == APPLICATION_TABLES - BILLING_TABLES - MEDIA_TABLES - GENERATION_TABLES
    assert billing_permissions(engine) == set()
    assert database_functions(engine) == {"forbid_append_only_mutation"}

    command.upgrade(config, "head")

    assert application_tables(engine) == APPLICATION_TABLES
    assert len(billing_permissions(engine)) == 5
    assert schema_drift(engine) == []


def media_permissions(engine: Engine) -> set[str]:
    query = text("SELECT key FROM permissions WHERE key IN ('render.testbed', 'voices.manage', 'music.manage')")
    with engine.connect() as connection:
        return set(connection.execute(query).scalars())


def default_voice_foreign_keys(engine: Engine) -> set[str]:
    query = text("SELECT conname FROM pg_constraint WHERE conname = 'fk_user_preferences_default_voice_id_voices'")
    with engine.connect() as connection:
        return set(connection.execute(query).scalars())


def test_media_revision_downgrades_cleanly_and_reapplies(scratch_database_url: str, engine: Engine) -> None:
    config = alembic_config_for(scratch_database_url)
    command.upgrade(config, "head")
    assert media_permissions(engine) == MEDIA_PERMISSIONS
    assert default_voice_foreign_keys(engine) == {"fk_user_preferences_default_voice_id_voices"}

    command.downgrade(config, "0005")

    assert current_revision(engine) == "0005"
    assert application_tables(engine) == APPLICATION_TABLES - MEDIA_TABLES - GENERATION_TABLES
    assert media_permissions(engine) == set()
    assert default_voice_foreign_keys(engine) == set()
    assert len(billing_permissions(engine)) == 5

    command.upgrade(config, "head")

    assert application_tables(engine) == APPLICATION_TABLES
    assert media_permissions(engine) == MEDIA_PERMISSIONS
    assert default_voice_foreign_keys(engine) == {"fk_user_preferences_default_voice_id_voices"}
    assert schema_drift(engine) == []


def generation_permissions(engine: Engine) -> set[str]:
    query = text(
        "SELECT key FROM permissions WHERE key IN ('prompts.manage', 'skills.manage', 'jobs.read_all', 'evals.run')"
    )
    with engine.connect() as connection:
        return set(connection.execute(query).scalars())


def checkpoint_tables(engine: Engine) -> set[str]:
    query = text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'langgraph'")
    with engine.connect() as connection:
        return set(connection.execute(query).scalars())


def checkpoint_versions(engine: Engine) -> list[int]:
    with engine.connect() as connection:
        return list(connection.execute(text("SELECT v FROM langgraph.checkpoint_migrations ORDER BY v")).scalars())


def usage_job_foreign_keys(engine: Engine) -> set[str]:
    query = text("SELECT conname FROM pg_constraint WHERE conname = 'fk_usage_records_job_id_jobs'")
    with engine.connect() as connection:
        return set(connection.execute(query).scalars())


def test_generation_revision_downgrades_cleanly_and_reapplies(scratch_database_url: str, engine: Engine) -> None:
    config = alembic_config_for(scratch_database_url)
    command.upgrade(config, "head")
    assert generation_permissions(engine) == GENERATION_PERMISSIONS
    assert checkpoint_tables(engine) == CHECKPOINT_TABLES
    assert checkpoint_versions(engine) == list(range(10))
    assert usage_job_foreign_keys(engine) == {"fk_usage_records_job_id_jobs"}

    command.downgrade(config, "0006")

    assert current_revision(engine) == "0006"
    assert application_tables(engine) == APPLICATION_TABLES - GENERATION_TABLES
    assert generation_permissions(engine) == set()
    assert checkpoint_tables(engine) == set()
    assert usage_job_foreign_keys(engine) == set()
    assert media_permissions(engine) == MEDIA_PERMISSIONS
    assert database_functions(engine) == {"forbid_append_only_mutation", "forbid_used_product_financial_change"}

    command.upgrade(config, "head")

    assert application_tables(engine) == APPLICATION_TABLES
    assert generation_permissions(engine) == GENERATION_PERMISSIONS
    assert checkpoint_tables(engine) == CHECKPOINT_TABLES
    assert usage_job_foreign_keys(engine) == {"fk_usage_records_job_id_jobs"}
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
