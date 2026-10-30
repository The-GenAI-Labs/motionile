from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from motionile.core.db import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_jobs_user_id_idempotency_key"),
        CheckConstraint("source IN ('catalog', 'query', 'mcp')", name="source"),
        CheckConstraint(
            "status IN ('queued', 'planning', 'awaiting_approval', 'voicing', 'generating', 'validating', "
            "'rendering', 'completed', 'failed', 'cancelled')",
            name="status",
        ),
        CheckConstraint("char_length(query) BETWEEN 1 AND 2000", name="query_length"),
        CheckConstraint("jsonb_typeof(options) = 'object'", name="options_object"),
        CheckConstraint("jsonb_typeof(reports) = 'object'", name="reports_object"),
        CheckConstraint(
            "credits_estimated >= 0 AND credits_reserved >= 0 AND (credits_charged IS NULL OR credits_charged >= 0)",
            name="credits_non_negative",
        ),
        CheckConstraint(
            "(status IN ('completed', 'failed', 'cancelled')) = (completed_at IS NOT NULL)",
            name="terminal_has_completed_at",
        ),
        CheckConstraint("status <> 'failed' OR error_code IS NOT NULL", name="failed_has_error"),
        CheckConstraint("error_code IS NULL OR error_code ~ '^[a-z][a-z0-9_]{1,59}$'", name="error_code_format"),
        CheckConstraint("error_message IS NULL OR char_length(error_message) <= 2000", name="error_message_length"),
        CheckConstraint("parent_job_id IS NULL OR parent_job_id <> id", name="not_own_parent"),
        Index("ix_jobs_user_id_created_at_id", "user_id", "created_at", "id"),
        Index(
            "ix_jobs_user_id_active",
            "user_id",
            postgresql_where=text("status NOT IN ('completed', 'failed', 'cancelled')"),
        ),
        Index(
            "ix_jobs_status_updated_at",
            "status",
            "updated_at",
            postgresql_where=text("status NOT IN ('completed', 'failed', 'cancelled', 'awaiting_approval')"),
        ),
        Index("ix_jobs_topic_id", "topic_id"),
        Index("ix_jobs_parent_job_id", "parent_job_id"),
        Index("ix_jobs_render_id", "render_id"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source: Mapped[str]
    topic_id: Mapped[UUID | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    parent_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    query: Mapped[str]
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(server_default=text("'queued'"))
    current_stage: Mapped[str | None]
    credits_estimated: Mapped[int] = mapped_column(BigInteger, server_default="0")
    credits_reserved: Mapped[int] = mapped_column(BigInteger, server_default="0")
    credits_charged: Mapped[int | None] = mapped_column(BigInteger)
    error_code: Mapped[str | None]
    error_message: Mapped[str | None]
    cancel_requested_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    render_id: Mapped[UUID | None] = mapped_column(ForeignKey("renders.id", ondelete="SET NULL"))
    idempotency_key: Mapped[str | None]
    reports: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class Storyboard(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "storyboards"
    __table_args__ = (
        UniqueConstraint("job_id", "version", name="uq_storyboards_job_id_version"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("origin IN ('planner', 'critic', 'regeneration', 'user')", name="origin"),
        CheckConstraint("jsonb_typeof(content) = 'object'", name="content_object"),
        CheckConstraint("approved_by IS NULL OR approved_at IS NOT NULL", name="approval_consistent"),
        Index("ix_storyboards_approved_by", "approved_by"),
    )

    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    origin: Mapped[str] = mapped_column(server_default=text("'planner'"))
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    approved_at: Mapped[datetime | None]
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Scene(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "scenes"
    __table_args__ = (
        UniqueConstraint(
            "storyboard_id",
            "position",
            name="uq_scenes_storyboard_id_position",
            deferrable=True,
            initially="IMMEDIATE",
        ),
        UniqueConstraint("storyboard_id", "scene_key", name="uq_scenes_storyboard_id_scene_key"),
        CheckConstraint("scene_key ~ '^[a-z][a-z0-9-]{0,31}$'", name="scene_key_format"),
        CheckConstraint("position >= 0", name="position_non_negative"),
        CheckConstraint("target_duration_ms BETWEEN 1000 AND 120000", name="target_duration_ms_range"),
        CheckConstraint(
            "actual_duration_ms IS NULL OR actual_duration_ms >= 0", name="actual_duration_ms_non_negative"
        ),
        CheckConstraint("status IN ('pending', 'voiced', 'generated', 'validated', 'failed')", name="status"),
        CheckConstraint("repair_attempts BETWEEN 0 AND 3", name="repair_attempts_range"),
        CheckConstraint(
            "word_timestamps IS NULL OR jsonb_typeof(word_timestamps) = 'array'", name="word_timestamps_array"
        ),
        CheckConstraint("module IS NULL OR jsonb_typeof(module) = 'object'", name="module_object"),
        CheckConstraint("jsonb_typeof(attempt_log) = 'array'", name="attempt_log_array"),
        CheckConstraint("error_code IS NULL OR error_code ~ '^[a-z][a-z0-9_]{1,59}$'", name="error_code_format"),
        CheckConstraint("char_length(narration) <= 2000", name="narration_length"),
        CheckConstraint("char_length(visual_brief) <= 4000", name="visual_brief_length"),
        Index("ix_scenes_audio_asset_id", "audio_asset_id"),
        Index("ix_scenes_html_asset_id", "html_asset_id"),
    )

    storyboard_id: Mapped[UUID] = mapped_column(ForeignKey("storyboards.id", ondelete="CASCADE"))
    scene_key: Mapped[str]
    position: Mapped[int] = mapped_column(Integer)
    narration: Mapped[str]
    visual_brief: Mapped[str]
    target_duration_ms: Mapped[int] = mapped_column(Integer)
    actual_duration_ms: Mapped[int | None]
    audio_asset_id: Mapped[UUID | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"))
    word_timestamps: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB(none_as_null=True))
    html_asset_id: Mapped[UUID | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"))
    module: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    status: Mapped[str] = mapped_column(server_default=text("'pending'"))
    repair_attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_fallback: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    attempt_log: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    error_code: Mapped[str | None]


class JobEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "job_events"
    __table_args__ = (
        CheckConstraint(r"type ~ '^[a-z][a-z_]*(\.[a-z][a-z_]*)*$' AND char_length(type) <= 64", name="type_format"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
        Index("ix_job_events_job_id_id", "job_id", "id"),
        Index("ix_job_events_created_at", "created_at"),
    )

    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    type: Mapped[str]
    stage: Mapped[str | None]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class ShareLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "share_links"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_share_links_slug"),
        CheckConstraint("slug ~ '^[A-Za-z0-9_-]{10,32}$'", name="slug_format"),
        CheckConstraint("view_count >= 0", name="view_count_non_negative"),
        Index("ix_share_links_job_id", "job_id"),
        Index("ix_share_links_rendition_id", "rendition_id"),
    )

    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    slug: Mapped[str]
    rendition_id: Mapped[UUID] = mapped_column(ForeignKey("renditions.id", ondelete="CASCADE"))
    is_public: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    expires_at: Mapped[datetime | None]
    view_count: Mapped[int] = mapped_column(BigInteger, server_default="0")
    revoked_at: Mapped[datetime | None]
