"""Create audit_log and idempotency_records with the append-only guard.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE_APPEND_ONLY_GUARD = """
CREATE FUNCTION forbid_append_only_mutation() RETURNS trigger
LANGUAGE plpgsql AS $guard$
BEGIN
    IF pg_trigger_depth() > 1 THEN
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END IF;
    IF TG_OP = 'DELETE' AND current_setting('motionile.allow_purge', true) = 'on' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'insufficient_privilege';
END
$guard$
"""

CREATE_AUDIT_LOG_TRIGGER = """
CREATE TRIGGER trg_audit_log_append_only
BEFORE UPDATE OR DELETE ON audit_log
FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation()
"""


def create_audit_log() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=True),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
        sa.CheckConstraint(
            "actor_type IN ('user', 'admin', 'system', 'api_key')", name=op.f("ck_audit_log_actor_type")
        ),
        sa.CheckConstraint(
            "action ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$' AND char_length(action) BETWEEN 3 AND 100",
            name=op.f("ck_audit_log_action_format"),
        ),
        sa.CheckConstraint(
            "target_type IS NULL OR char_length(target_type) <= 64", name=op.f("ck_audit_log_target_type_length")
        ),
        sa.CheckConstraint(
            "target_id IS NULL OR char_length(target_id) <= 128", name=op.f("ck_audit_log_target_id_length")
        ),
        sa.CheckConstraint(
            "user_agent IS NULL OR char_length(user_agent) <= 512", name=op.f("ck_audit_log_user_agent_length")
        ),
        sa.CheckConstraint(
            "request_id IS NULL OR char_length(request_id) <= 64", name=op.f("ck_audit_log_request_id_length")
        ),
        sa.CheckConstraint("jsonb_typeof(metadata) = 'object'", name=op.f("ck_audit_log_metadata_object")),
    )
    op.create_index("ix_audit_log_created_at_id", "audit_log", ["created_at", "id"])
    op.create_index("ix_audit_log_actor_user_id_created_at", "audit_log", ["actor_user_id", "created_at"])
    op.create_index(
        "ix_audit_log_target_type_target_id_created_at", "audit_log", ["target_type", "target_id", "created_at"]
    )
    op.create_index("ix_audit_log_action_created_at", "audit_log", ["action", "created_at"])
    op.execute(CREATE_AUDIT_LOG_TRIGGER)


def create_idempotency_records() -> None:
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'in_progress'"), nullable=False),
        sa.Column("response_status", sa.SmallInteger(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(), nullable=True),
        sa.Column("response_headers", postgresql.JSONB(), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_idempotency_records"),
        sa.UniqueConstraint(
            "scope",
            "user_id",
            "key",
            name="uq_idempotency_records_scope_user_id_key",
            postgresql_nulls_not_distinct=True,
        ),
        sa.CheckConstraint("status IN ('in_progress', 'completed')", name=op.f("ck_idempotency_records_status")),
        sa.CheckConstraint("char_length(scope) BETWEEN 1 AND 100", name=op.f("ck_idempotency_records_scope_length")),
        sa.CheckConstraint("key ~ '^[\\x21-\\x7E]{1,255}$'", name=op.f("ck_idempotency_records_key_format")),
        sa.CheckConstraint("octet_length(request_hash) = 32", name=op.f("ck_idempotency_records_request_hash_length")),
        sa.CheckConstraint(
            "response_status IS NULL OR response_status BETWEEN 100 AND 599",
            name=op.f("ck_idempotency_records_response_status_range"),
        ),
        sa.CheckConstraint(
            "status <> 'completed' OR response_status IS NOT NULL",
            name=op.f("ck_idempotency_records_completed_has_response"),
        ),
        sa.CheckConstraint(
            "status <> 'in_progress' OR locked_until IS NOT NULL",
            name=op.f("ck_idempotency_records_in_progress_has_lock"),
        ),
    )
    op.create_index("ix_idempotency_records_user_id", "idempotency_records", ["user_id"])
    op.create_index("ix_idempotency_records_expires_at", "idempotency_records", ["expires_at"])


def upgrade() -> None:
    op.execute(CREATE_APPEND_ONLY_GUARD)
    create_audit_log()
    create_idempotency_records()


def downgrade() -> None:
    op.drop_table("idempotency_records")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_append_only ON audit_log")
    op.drop_table("audit_log")
    op.execute("DROP FUNCTION IF EXISTS forbid_append_only_mutation()")
