from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, SmallInteger, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from motionile.core.db import Base, TimestampMixin


class SystemSetting(TimestampMixin, Base):
    __tablename__ = "system_settings"
    __table_args__ = (
        CheckConstraint("key ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$'", name="key_format"),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_system_settings_updated_by", "updated_by"),
    )

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[object] = mapped_column(JSONB())
    description: Mapped[str | None]
    version: Mapped[int] = mapped_column(server_default="1")
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class FeatureFlag(TimestampMixin, Base):
    __tablename__ = "feature_flags"
    __table_args__ = (
        CheckConstraint("key ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$'", name="key_format"),
        CheckConstraint("rollout_percentage BETWEEN 0 AND 100", name="rollout_percentage_range"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("jsonb_typeof(rules) = 'array'", name="rules_array"),
        Index("ix_feature_flags_updated_by", "updated_by"),
    )

    key: Mapped[str] = mapped_column(primary_key=True)
    description: Mapped[str | None]
    enabled: Mapped[bool] = mapped_column(server_default=text("false"))
    rollout_percentage: Mapped[int] = mapped_column(SmallInteger(), server_default="0")
    version: Mapped[int] = mapped_column(server_default="1")
    rules: Mapped[list[dict[str, object]]] = mapped_column(JSONB(), server_default=text("'[]'::jsonb"))
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
