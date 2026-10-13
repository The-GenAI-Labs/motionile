from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Index
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from motionile.core.db import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class AuditLogEntry(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint("actor_type IN ('user', 'admin', 'system', 'api_key')", name="actor_type"),
        CheckConstraint(
            "action ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$' AND char_length(action) BETWEEN 3 AND 100",
            name="action_format",
        ),
        CheckConstraint("target_type IS NULL OR char_length(target_type) <= 64", name="target_type_length"),
        CheckConstraint("target_id IS NULL OR char_length(target_id) <= 128", name="target_id_length"),
        CheckConstraint("user_agent IS NULL OR char_length(user_agent) <= 512", name="user_agent_length"),
        CheckConstraint("request_id IS NULL OR char_length(request_id) <= 64", name="request_id_length"),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_object"),
        Index("ix_audit_log_created_at_id", "created_at", "id"),
        Index("ix_audit_log_actor_user_id_created_at", "actor_user_id", "created_at"),
        Index("ix_audit_log_target_type_target_id_created_at", "target_type", "target_id", "created_at"),
        Index("ix_audit_log_action_created_at", "action", "created_at"),
    )

    actor_user_id: Mapped[UUID | None]
    actor_type: Mapped[str]
    action: Mapped[str]
    target_type: Mapped[str | None]
    target_id: Mapped[str | None]
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None]
    request_id: Mapped[str | None]
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, server_default="{}")
