from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from motionile.core.config import get_settings

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

EMBEDDING_DIMENSIONS = get_settings().ai.embedding_dimensions
TERMINAL_JOB_STATUSES = "('completed', 'failed', 'cancelled')"
GENERATION_PERMISSIONS = (
    ("prompts.manage", "Create, evaluate, activate and roll back prompt versions"),
    ("skills.manage", "Curate system skills"),
    ("jobs.read_all", "Read the generation jobs of every user"),
    ("evals.run", "Start evaluation runs"),
)
FIRST_GENERATION_PERMISSION_INDEX = 20
INSERT_ADMIN_GENERATION_PERMISSIONS = (
    "INSERT INTO role_permissions (role_id, permission_id) "
    "SELECT roles.id, permissions.id FROM roles CROSS JOIN permissions "
    "WHERE roles.key = 'admin' AND permissions.key IN ('jobs.read_all', 'skills.manage')"
)
DELETE_GENERATION_PERMISSIONS = (
    "DELETE FROM permissions WHERE key IN ('prompts.manage', 'skills.manage', 'jobs.read_all', 'evals.run')"
)
CREATE_JOB_EVENTS_TRIGGER = (
    "CREATE TRIGGER trg_job_events_append_only BEFORE UPDATE OR DELETE ON job_events "
    "FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation()"
)
CHECKPOINT_SCHEMA = "langgraph"
CHECKPOINT_MIGRATIONS = (
    """CREATE TABLE checkpoint_migrations (
    v INTEGER PRIMARY KEY
)""",
    """CREATE TABLE checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
)""",
    """CREATE TABLE checkpoint_blobs (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL,
    version TEXT NOT NULL,
    type TEXT NOT NULL,
    blob BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
)""",
    """CREATE TABLE checkpoint_writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    type TEXT,
    blob BYTEA NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
)""",
    "ALTER TABLE checkpoint_blobs ALTER COLUMN blob DROP NOT NULL",
    "SELECT 1",
    "CREATE INDEX IF NOT EXISTS checkpoints_thread_id_idx ON checkpoints(thread_id)",
    "CREATE INDEX IF NOT EXISTS checkpoint_blobs_thread_id_idx ON checkpoint_blobs(thread_id)",
    "CREATE INDEX IF NOT EXISTS checkpoint_writes_thread_id_idx ON checkpoint_writes(thread_id)",
    "ALTER TABLE checkpoint_writes ADD COLUMN IF NOT EXISTS task_path TEXT NOT NULL DEFAULT ''",
)


def timestamps() -> list[sa.Column[datetime]]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def created_at() -> sa.Column[datetime]:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def create_jobs() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("topic_id", sa.Uuid(), nullable=True),
        sa.Column("parent_job_id", sa.Uuid(), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column(
            "options", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("current_stage", sa.Text(), nullable=True),
        sa.Column("credits_estimated", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("credits_reserved", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("credits_charged", sa.BigInteger(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("render_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column(
            "reports", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        *timestamps(),
        sa.CheckConstraint("source IN ('catalog', 'query', 'mcp')", name=op.f("ck_jobs_source")),
        sa.CheckConstraint(
            "status IN ('queued', 'planning', 'awaiting_approval', 'voicing', 'generating', 'validating', "
            "'rendering', 'completed', 'failed', 'cancelled')",
            name=op.f("ck_jobs_status"),
        ),
        sa.CheckConstraint("char_length(query) BETWEEN 1 AND 2000", name=op.f("ck_jobs_query_length")),
        sa.CheckConstraint("jsonb_typeof(options) = 'object'", name=op.f("ck_jobs_options_object")),
        sa.CheckConstraint("jsonb_typeof(reports) = 'object'", name=op.f("ck_jobs_reports_object")),
        sa.CheckConstraint(
            "credits_estimated >= 0 AND credits_reserved >= 0 AND (credits_charged IS NULL OR credits_charged >= 0)",
            name=op.f("ck_jobs_credits_non_negative"),
        ),
        sa.CheckConstraint(
            f"(status IN {TERMINAL_JOB_STATUSES}) = (completed_at IS NOT NULL)",
            name=op.f("ck_jobs_terminal_has_completed_at"),
        ),
        sa.CheckConstraint("status <> 'failed' OR error_code IS NOT NULL", name=op.f("ck_jobs_failed_has_error")),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[a-z][a-z0-9_]{1,59}$'", name=op.f("ck_jobs_error_code_format")
        ),
        sa.CheckConstraint(
            "error_message IS NULL OR char_length(error_message) <= 2000", name=op.f("ck_jobs_error_message_length")
        ),
        sa.CheckConstraint("parent_job_id IS NULL OR parent_job_id <> id", name=op.f("ck_jobs_not_own_parent")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_jobs_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], name=op.f("fk_jobs_topic_id_topics"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["parent_job_id"], ["jobs.id"], name=op.f("fk_jobs_parent_job_id_jobs"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["render_id"], ["renders.id"], name=op.f("fk_jobs_render_id_renders"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("user_id", "idempotency_key", name=op.f("uq_jobs_user_id_idempotency_key")),
    )
    op.create_index(op.f("ix_jobs_user_id_created_at_id"), "jobs", ["user_id", "created_at", "id"])
    op.create_index(
        op.f("ix_jobs_user_id_active"),
        "jobs",
        ["user_id"],
        postgresql_where=sa.text(f"status NOT IN {TERMINAL_JOB_STATUSES}"),
    )
    op.create_index(
        op.f("ix_jobs_status_updated_at"),
        "jobs",
        ["status", "updated_at"],
        postgresql_where=sa.text("status NOT IN ('completed', 'failed', 'cancelled', 'awaiting_approval')"),
    )
    op.create_index(op.f("ix_jobs_topic_id"), "jobs", ["topic_id"])
    op.create_index(op.f("ix_jobs_parent_job_id"), "jobs", ["parent_job_id"])
    op.create_index(op.f("ix_jobs_render_id"), "jobs", ["render_id"])


def create_storyboards() -> None:
    op.create_table(
        "storyboards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("origin", sa.Text(), server_default=sa.text("'planner'"), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        *timestamps(),
        sa.CheckConstraint("version >= 1", name=op.f("ck_storyboards_version_positive")),
        sa.CheckConstraint(
            "origin IN ('planner', 'critic', 'regeneration', 'user')", name=op.f("ck_storyboards_origin")
        ),
        sa.CheckConstraint("jsonb_typeof(content) = 'object'", name=op.f("ck_storyboards_content_object")),
        sa.CheckConstraint(
            "approved_by IS NULL OR approved_at IS NOT NULL", name=op.f("ck_storyboards_approval_consistent")
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_storyboards_job_id_jobs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["approved_by"], ["users.id"], name=op.f("fk_storyboards_approved_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_storyboards")),
        sa.UniqueConstraint("job_id", "version", name=op.f("uq_storyboards_job_id_version")),
    )
    op.create_index(op.f("ix_storyboards_approved_by"), "storyboards", ["approved_by"])


def create_scenes() -> None:
    op.create_table(
        "scenes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("storyboard_id", sa.Uuid(), nullable=False),
        sa.Column("scene_key", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("narration", sa.Text(), nullable=False),
        sa.Column("visual_brief", sa.Text(), nullable=False),
        sa.Column("target_duration_ms", sa.Integer(), nullable=False),
        sa.Column("actual_duration_ms", sa.Integer(), nullable=True),
        sa.Column("audio_asset_id", sa.Uuid(), nullable=True),
        sa.Column("word_timestamps", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("html_asset_id", sa.Uuid(), nullable=True),
        sa.Column("module", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("repair_attempts", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("is_fallback", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "attempt_log",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_code", sa.Text(), nullable=True),
        *timestamps(),
        sa.CheckConstraint("scene_key ~ '^[a-z][a-z0-9-]{0,31}$'", name=op.f("ck_scenes_scene_key_format")),
        sa.CheckConstraint("position >= 0", name=op.f("ck_scenes_position_non_negative")),
        sa.CheckConstraint(
            "target_duration_ms BETWEEN 1000 AND 120000", name=op.f("ck_scenes_target_duration_ms_range")
        ),
        sa.CheckConstraint(
            "actual_duration_ms IS NULL OR actual_duration_ms >= 0",
            name=op.f("ck_scenes_actual_duration_ms_non_negative"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'voiced', 'generated', 'validated', 'failed')", name=op.f("ck_scenes_status")
        ),
        sa.CheckConstraint("repair_attempts BETWEEN 0 AND 3", name=op.f("ck_scenes_repair_attempts_range")),
        sa.CheckConstraint(
            "word_timestamps IS NULL OR jsonb_typeof(word_timestamps) = 'array'",
            name=op.f("ck_scenes_word_timestamps_array"),
        ),
        sa.CheckConstraint("module IS NULL OR jsonb_typeof(module) = 'object'", name=op.f("ck_scenes_module_object")),
        sa.CheckConstraint("jsonb_typeof(attempt_log) = 'array'", name=op.f("ck_scenes_attempt_log_array")),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[a-z][a-z0-9_]{1,59}$'", name=op.f("ck_scenes_error_code_format")
        ),
        sa.CheckConstraint("char_length(narration) <= 2000", name=op.f("ck_scenes_narration_length")),
        sa.CheckConstraint("char_length(visual_brief) <= 4000", name=op.f("ck_scenes_visual_brief_length")),
        sa.ForeignKeyConstraint(
            ["storyboard_id"], ["storyboards.id"], name=op.f("fk_scenes_storyboard_id_storyboards"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["audio_asset_id"], ["assets.id"], name=op.f("fk_scenes_audio_asset_id_assets"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["html_asset_id"], ["assets.id"], name=op.f("fk_scenes_html_asset_id_assets"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenes")),
        sa.UniqueConstraint(
            "storyboard_id",
            "position",
            name=op.f("uq_scenes_storyboard_id_position"),
            deferrable=True,
            initially="IMMEDIATE",
        ),
        sa.UniqueConstraint("storyboard_id", "scene_key", name=op.f("uq_scenes_storyboard_id_scene_key")),
    )
    op.create_index(op.f("ix_scenes_audio_asset_id"), "scenes", ["audio_asset_id"])
    op.create_index(op.f("ix_scenes_html_asset_id"), "scenes", ["html_asset_id"])


def create_job_events() -> None:
    op.create_table(
        "job_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        created_at(),
        sa.CheckConstraint(
            r"type ~ '^[a-z][a-z_]*(\.[a-z][a-z_]*)*$' AND char_length(type) <= 64",
            name=op.f("ck_job_events_type_format"),
        ),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name=op.f("ck_job_events_payload_object")),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_job_events_job_id_jobs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_events")),
    )
    op.create_index(op.f("ix_job_events_job_id_id"), "job_events", ["job_id", "id"])
    op.create_index(op.f("ix_job_events_created_at"), "job_events", ["created_at"])
    op.execute(CREATE_JOB_EVENTS_TRIGGER)


def create_share_links() -> None:
    op.create_table(
        "share_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("rendition_id", sa.Uuid(), nullable=False),
        sa.Column("is_public", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("view_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint("slug ~ '^[A-Za-z0-9_-]{10,32}$'", name=op.f("ck_share_links_slug_format")),
        sa.CheckConstraint("view_count >= 0", name=op.f("ck_share_links_view_count_non_negative")),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_share_links_job_id_jobs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["rendition_id"],
            ["renditions.id"],
            name=op.f("fk_share_links_rendition_id_renditions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_share_links")),
        sa.UniqueConstraint("slug", name=op.f("uq_share_links_slug")),
    )
    op.create_index(op.f("ix_share_links_job_id"), "share_links", ["job_id"])
    op.create_index(op.f("ix_share_links_rendition_id"), "share_links", ["rendition_id"])


def create_prompt_templates() -> None:
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active_version_id", sa.Uuid(), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            r"key ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$'", name=op.f("ck_prompt_templates_key_format")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_templates")),
        sa.UniqueConstraint("key", name=op.f("uq_prompt_templates_key")),
    )
    op.create_index(op.f("ix_prompt_templates_active_version_id"), "prompt_templates", ["active_version_id"])


def create_prompt_versions() -> None:
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "variables", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("checksum", sa.LargeBinary(), nullable=False),
        sa.Column("canary", sa.Text(), nullable=False),
        sa.Column("eval_status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("eval_report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "eval_status IN ('pending', 'passed', 'failed')", name=op.f("ck_prompt_versions_eval_status")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_prompt_versions_version_positive")),
        sa.CheckConstraint("octet_length(checksum) = 32", name=op.f("ck_prompt_versions_checksum_length")),
        sa.CheckConstraint("jsonb_typeof(variables) = 'array'", name=op.f("ck_prompt_versions_variables_array")),
        sa.CheckConstraint(
            "eval_report IS NULL OR jsonb_typeof(eval_report) = 'object'",
            name=op.f("ck_prompt_versions_eval_report_object"),
        ),
        sa.CheckConstraint("char_length(canary) BETWEEN 16 AND 64", name=op.f("ck_prompt_versions_canary_length")),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["prompt_templates.id"],
            name=op.f("fk_prompt_versions_template_id_prompt_templates"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_prompt_versions_created_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_versions")),
        sa.UniqueConstraint("template_id", "version", name=op.f("uq_prompt_versions_template_id_version")),
        sa.UniqueConstraint("template_id", "checksum", name=op.f("uq_prompt_versions_template_id_checksum")),
    )
    op.create_index(op.f("ix_prompt_versions_created_by"), "prompt_versions", ["created_by"])
    op.create_foreign_key(
        op.f("fk_prompt_templates_active_version_id_prompt_versions"),
        "prompt_templates",
        "prompt_versions",
        ["active_version_id"],
        ["id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )


def create_eval_runs() -> None:
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("suite", sa.Text(), nullable=False),
        sa.Column("dataset_version", sa.Text(), nullable=False),
        sa.Column(
            "prompt_version_ids",
            postgresql.ARRAY(sa.Uuid()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "model_configuration",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "scores", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'running'"), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint("status IN ('running', 'finished', 'errored')", name=op.f("ck_eval_runs_status")),
        sa.CheckConstraint("trigger IN ('ci', 'nightly', 'admin')", name=op.f("ck_eval_runs_trigger")),
        sa.CheckConstraint("suite ~ '^[a-z][a-z0-9_.-]{0,59}$'", name=op.f("ck_eval_runs_suite_format")),
        sa.CheckConstraint(
            "dataset_version ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$'", name=op.f("ck_eval_runs_dataset_version_format")
        ),
        sa.CheckConstraint("cardinality(prompt_version_ids) <= 100", name=op.f("ck_eval_runs_prompt_version_ids_size")),
        sa.CheckConstraint(
            "jsonb_typeof(model_configuration) = 'object'", name=op.f("ck_eval_runs_model_configuration_object")
        ),
        sa.CheckConstraint("jsonb_typeof(scores) = 'object'", name=op.f("ck_eval_runs_scores_object")),
        sa.CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)", name=op.f("ck_eval_runs_finished_consistent")
        ),
        sa.CheckConstraint("(status = 'finished') = (passed IS NOT NULL)", name=op.f("ck_eval_runs_passed_consistent")),
        sa.CheckConstraint(
            "(status = 'errored') = (error_code IS NOT NULL)", name=op.f("ck_eval_runs_errored_has_error")
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[a-z][a-z0-9_]{1,59}$'", name=op.f("ck_eval_runs_error_code_format")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_eval_runs_created_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_runs")),
    )
    op.create_index(op.f("ix_eval_runs_suite_created_at"), "eval_runs", ["suite", "created_at"])
    op.create_index(op.f("ix_eval_runs_created_by"), "eval_runs", ["created_by"])
    op.create_index(
        op.f("ix_eval_runs_prompt_version_ids"), "eval_runs", ["prompt_version_ids"], postgresql_using="gin"
    )


def create_skills() -> None:
    op.create_table(
        "skills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("visibility", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint("visibility IN ('system', 'private')", name=op.f("ck_skills_visibility")),
        sa.CheckConstraint("status IN ('draft', 'active', 'archived')", name=op.f("ck_skills_status")),
        sa.CheckConstraint("(visibility = 'system') = (owner_user_id IS NULL)", name=op.f("ck_skills_ownership")),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND char_length(slug) <= 64", name=op.f("ck_skills_slug_format")
        ),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 64", name=op.f("ck_skills_name_length")),
        sa.CheckConstraint("char_length(description) BETWEEN 1 AND 1024", name=op.f("ck_skills_description_length")),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], name=op.f("fk_skills_owner_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_skills")),
    )
    op.create_index(
        op.f("ix_skills_owner_user_id_slug"),
        "skills",
        ["owner_user_id", "slug"],
        unique=True,
        postgresql_nulls_not_distinct=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        op.f("ix_skills_owner_user_id_created_at"),
        "skills",
        ["owner_user_id", "created_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(op.f("ix_skills_owner_user_id"), "skills", ["owner_user_id"])
    op.create_index(op.f("ix_skills_current_version_id"), "skills", ["current_version_id"])


def create_skill_versions() -> None:
    op.create_table(
        "skill_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("frontmatter", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("checksum", sa.LargeBinary(), nullable=False),
        sa.Column("scan_status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("scan_report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "scan_status IN ('pending', 'passed', 'flagged')", name=op.f("ck_skill_versions_scan_status")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_skill_versions_version_positive")),
        sa.CheckConstraint("octet_length(checksum) = 32", name=op.f("ck_skill_versions_checksum_length")),
        sa.CheckConstraint("jsonb_typeof(frontmatter) = 'object'", name=op.f("ck_skill_versions_frontmatter_object")),
        sa.CheckConstraint("char_length(body_md) <= 100000", name=op.f("ck_skill_versions_body_md_length")),
        sa.CheckConstraint(
            "(scan_status = 'pending') = (scanned_at IS NULL)", name=op.f("ck_skill_versions_scanned_consistent")
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skills.id"], name=op.f("fk_skill_versions_skill_id_skills"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_skill_versions_created_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_skill_versions")),
        sa.UniqueConstraint("skill_id", "version", name=op.f("uq_skill_versions_skill_id_version")),
    )
    op.create_index(op.f("ix_skill_versions_created_by"), "skill_versions", ["created_by"])
    op.create_index(
        op.f("ix_skill_versions_scan_status_created_at"),
        "skill_versions",
        ["scan_status", "created_at"],
        postgresql_where=sa.text("scan_status = 'pending'"),
    )
    op.create_foreign_key(
        op.f("fk_skills_current_version_id_skill_versions"),
        "skills",
        "skill_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
        deferrable=True,
        initially="DEFERRED",
    )


def create_skill_files() -> None:
    op.create_table(
        "skill_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("skill_version_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.LargeBinary(), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "path ~ '^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$' AND path NOT LIKE '%..%' AND char_length(path) <= 255",
            name=op.f("ck_skill_files_path_safe"),
        ),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_skill_files_size_bytes_non_negative")),
        sa.CheckConstraint("octet_length(sha256) = 32", name=op.f("ck_skill_files_sha256_length")),
        sa.ForeignKeyConstraint(
            ["skill_version_id"],
            ["skill_versions.id"],
            name=op.f("fk_skill_files_skill_version_id_skill_versions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["assets.id"], name=op.f("fk_skill_files_asset_id_assets"), ondelete="NO ACTION"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_skill_files")),
        sa.UniqueConstraint("skill_version_id", "path", name=op.f("uq_skill_files_skill_version_id_path")),
    )
    op.create_index(op.f("ix_skill_files_asset_id"), "skill_files", ["asset_id"])


def create_skill_embeddings() -> None:
    op.create_table(
        "skill_embeddings",
        sa.Column("skill_version_id", sa.Uuid(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["skill_version_id"],
            ["skill_versions.id"],
            name=op.f("fk_skill_embeddings_skill_version_id_skill_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("skill_version_id", name=op.f("pk_skill_embeddings")),
    )
    op.create_index(
        op.f("ix_skill_embeddings_embedding"),
        "skill_embeddings",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def create_checkpoint_schema() -> None:
    op.execute(f"CREATE SCHEMA {CHECKPOINT_SCHEMA}")
    op.execute(f"SET LOCAL search_path TO {CHECKPOINT_SCHEMA}")
    for statement in CHECKPOINT_MIGRATIONS:
        op.execute(statement)
    op.execute(
        sa.text("INSERT INTO checkpoint_migrations (v) SELECT generate_series(0, :last_version)").bindparams(
            last_version=len(CHECKPOINT_MIGRATIONS) - 1
        )
    )
    op.execute("SET LOCAL search_path TO DEFAULT")


def seed_permissions() -> None:
    permission_table = sa.table(
        "permissions",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.Text()),
        sa.column("description", sa.Text()),
    )
    op.bulk_insert(
        permission_table,
        [
            {
                "id": UUID(f"0199eb00-0000-7000-8000-{index:012d}"),
                "key": key,
                "description": description,
            }
            for index, (key, description) in enumerate(GENERATION_PERMISSIONS, start=FIRST_GENERATION_PERMISSION_INDEX)
        ],
    )
    op.execute(INSERT_ADMIN_GENERATION_PERMISSIONS)


def upgrade() -> None:
    create_jobs()
    create_storyboards()
    create_scenes()
    create_job_events()
    create_share_links()
    create_prompt_templates()
    create_prompt_versions()
    create_eval_runs()
    create_skills()
    create_skill_versions()
    create_skill_files()
    create_skill_embeddings()
    op.create_foreign_key(
        op.f("fk_usage_records_job_id_jobs"), "usage_records", "jobs", ["job_id"], ["id"], ondelete="SET NULL"
    )
    create_checkpoint_schema()
    seed_permissions()


def downgrade() -> None:
    op.execute(DELETE_GENERATION_PERMISSIONS)
    op.execute(f"DROP SCHEMA IF EXISTS {CHECKPOINT_SCHEMA} CASCADE")
    op.drop_constraint(op.f("fk_usage_records_job_id_jobs"), "usage_records", type_="foreignkey")
    op.drop_table("skill_embeddings")
    op.drop_table("skill_files")
    op.drop_constraint(op.f("fk_skills_current_version_id_skill_versions"), "skills", type_="foreignkey")
    op.drop_table("skill_versions")
    op.drop_table("skills")
    op.drop_table("eval_runs")
    op.drop_constraint(
        op.f("fk_prompt_templates_active_version_id_prompt_versions"), "prompt_templates", type_="foreignkey"
    )
    op.drop_table("prompt_versions")
    op.drop_table("prompt_templates")
    op.drop_table("share_links")
    op.execute("DROP TRIGGER IF EXISTS trg_job_events_append_only ON job_events")
    op.drop_table("job_events")
    op.drop_table("scenes")
    op.drop_table("storyboards")
    op.drop_table("jobs")
