from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, UniqueConstraint, Uuid, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from motionile.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PromptTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "prompt_templates"
    __table_args__ = (
        UniqueConstraint("key", name="uq_prompt_templates_key"),
        CheckConstraint(r"key ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$'", name="key_format"),
        Index("ix_prompt_templates_active_version_id", "active_version_id"),
    )

    key: Mapped[str]
    description: Mapped[str | None]
    active_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="RESTRICT", deferrable=True, initially="DEFERRED", use_alter=True)
    )


class PromptVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("template_id", "version", name="uq_prompt_versions_template_id_version"),
        UniqueConstraint("template_id", "checksum", name="uq_prompt_versions_template_id_checksum"),
        CheckConstraint("eval_status IN ('pending', 'passed', 'failed')", name="eval_status"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("octet_length(checksum) = 32", name="checksum_length"),
        CheckConstraint("jsonb_typeof(variables) = 'array'", name="variables_array"),
        CheckConstraint("eval_report IS NULL OR jsonb_typeof(eval_report) = 'object'", name="eval_report_object"),
        CheckConstraint("char_length(canary) BETWEEN 16 AND 64", name="canary_length"),
        Index("ix_prompt_versions_created_by", "created_by"),
    )

    template_id: Mapped[UUID] = mapped_column(ForeignKey("prompt_templates.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    body: Mapped[str]
    variables: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    checksum: Mapped[bytes]
    canary: Mapped[str]
    eval_status: Mapped[str] = mapped_column(server_default=text("'pending'"))
    eval_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class EvalRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "eval_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'finished', 'errored')", name="status"),
        CheckConstraint("trigger IN ('ci', 'nightly', 'admin')", name="trigger"),
        CheckConstraint("suite ~ '^[a-z][a-z0-9_.-]{0,59}$'", name="suite_format"),
        CheckConstraint("dataset_version ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$'", name="dataset_version_format"),
        CheckConstraint("cardinality(prompt_version_ids) <= 100", name="prompt_version_ids_size"),
        CheckConstraint("jsonb_typeof(model_configuration) = 'object'", name="model_configuration_object"),
        CheckConstraint("jsonb_typeof(scores) = 'object'", name="scores_object"),
        CheckConstraint("(status = 'running') = (finished_at IS NULL)", name="finished_consistent"),
        CheckConstraint("(status = 'finished') = (passed IS NOT NULL)", name="passed_consistent"),
        CheckConstraint("(status = 'errored') = (error_code IS NOT NULL)", name="errored_has_error"),
        CheckConstraint("error_code IS NULL OR error_code ~ '^[a-z][a-z0-9_]{1,59}$'", name="error_code_format"),
        Index("ix_eval_runs_suite_created_at", "suite", "created_at"),
        Index("ix_eval_runs_created_by", "created_by"),
        Index("ix_eval_runs_prompt_version_ids", "prompt_version_ids", postgresql_using="gin"),
    )

    suite: Mapped[str]
    dataset_version: Mapped[str]
    prompt_version_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid()), server_default=text("'{}'"))
    models_used: Mapped[dict[str, Any]] = mapped_column(
        "model_configuration", JSONB, server_default=text("'{}'::jsonb")
    )
    scores: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    passed: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(server_default=text("'running'"))
    error_code: Mapped[str | None]
    trigger: Mapped[str]
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    finished_at: Mapped[datetime | None]
