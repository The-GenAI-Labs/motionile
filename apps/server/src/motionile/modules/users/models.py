from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from motionile.core.db import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('pending_verification', 'active', 'suspended', 'deleted')", name="status"),
        CheckConstraint("(status = 'deleted') = (deleted_at IS NOT NULL)", name="deleted_consistent"),
        CheckConstraint("name IS NULL OR char_length(name) BETWEEN 1 AND 120", name="name_length"),
        CheckConstraint(
            "avatar_storage_key IS NULL OR char_length(avatar_storage_key) <= 512", name="avatar_storage_key_length"
        ),
        CheckConstraint("locale ~ '^[a-z]{2,3}(-[A-Z]{2})?$'", name="locale_format"),
        Index("ix_users_created_at_id", "created_at", "id", postgresql_where=text("deleted_at IS NULL")),
        Index("ix_users_status_created_at", "status", "created_at", postgresql_where=text("deleted_at IS NULL")),
        Index("ix_users_deleted_at", "deleted_at", postgresql_where=text("deleted_at IS NOT NULL")),
    )

    name: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default="pending_verification")
    avatar_storage_key: Mapped[str | None]
    locale: Mapped[str] = mapped_column(server_default="en-IN")
    last_login_at: Mapped[datetime | None]


class UserContact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_contacts"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "value"),
        CheckConstraint("kind IN ('email', 'phone')", name="kind"),
        CheckConstraint(
            r"kind <> 'email' OR (value ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' AND char_length(value) <= 254)",
            name="email_format",
        ),
        CheckConstraint(r"kind <> 'phone' OR value ~ '^\+[1-9][0-9]{6,14}$'", name="phone_format"),
        Index(
            "ix_user_contacts_kind_value_verified",
            "kind",
            "value",
            unique=True,
            postgresql_where=text("verified_at IS NOT NULL"),
        ),
        Index(
            "ix_user_contacts_user_id_kind_primary", "user_id", "kind", unique=True, postgresql_where=text("is_primary")
        ),
        Index("ix_user_contacts_kind_value", "kind", "value"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str]
    value: Mapped[str] = mapped_column(CITEXT())
    verified_at: Mapped[datetime | None]
    is_primary: Mapped[bool] = mapped_column(server_default=text("false"))


class UserPreference(TimestampMixin, Base):
    __tablename__ = "user_preferences"
    __table_args__ = (
        CheckConstraint("pace IN ('slow', 'normal', 'fast')", name="pace"),
        CheckConstraint("depth IN ('overview', 'standard', 'deep')", name="depth"),
        CheckConstraint("default_aspect IN ('16:9', '9:16', '1:1')", name="default_aspect"),
        CheckConstraint("language ~ '^[a-z]{2,3}(-[A-Z]{2})?$'", name="language_format"),
        CheckConstraint(
            "default_style IS NULL OR default_style ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="default_style_format"
        ),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    default_style: Mapped[str | None]
    pace: Mapped[str] = mapped_column(server_default="normal")
    language: Mapped[str] = mapped_column(server_default="en")
    depth: Mapped[str] = mapped_column(server_default="standard")
    default_voice_id: Mapped[UUID | None]
    default_aspect: Mapped[str] = mapped_column(server_default="16:9")
    captions_enabled: Mapped[bool] = mapped_column(server_default=text("true"))
