from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import CITEXT, INET
from sqlalchemy.orm import Mapped, mapped_column

from motionile.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Credential(TimestampMixin, Base):
    __tablename__ = "credentials"
    __table_args__ = (CheckConstraint("password_hash LIKE '$argon2id$%'", name="password_hash_argon2id"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    password_hash: Mapped[str]
    password_updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class OAuthIdentity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "oauth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject"),
        CheckConstraint("provider IN ('google', 'github', 'microsoft')", name="provider"),
        CheckConstraint("char_length(subject) BETWEEN 1 AND 255", name="subject_length"),
        Index("ix_oauth_identities_user_id", "user_id"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str]
    subject: Mapped[str]
    email: Mapped[str | None] = mapped_column(CITEXT())
    email_verified: Mapped[bool] = mapped_column(server_default=text("false"))
    last_login_at: Mapped[datetime | None]


class Session(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("octet_length(token_hash) = 32", name="token_hash_length"),
        CheckConstraint("idle_expires_at <= absolute_expires_at", name="expiry_order"),
        CheckConstraint(
            "revoke_reason IS NULL OR revoke_reason IN "
            "('logout', 'logout_all', 'reuse_detected', 'password_changed', 'admin', 'user_suspended')",
            name="revoke_reason",
        ),
        CheckConstraint("(revoked_at IS NULL) = (revoke_reason IS NULL)", name="revocation_consistent"),
        CheckConstraint("user_agent IS NULL OR char_length(user_agent) <= 512", name="user_agent_length"),
        Index(
            "ix_sessions_user_id_created_at",
            "user_id",
            "created_at",
            postgresql_where=text("revoked_at IS NULL AND rotated_at IS NULL"),
        ),
        Index("ix_sessions_user_id", "user_id"),
        Index("ix_sessions_family_id", "family_id"),
        Index("ix_sessions_parent_id", "parent_id"),
        Index("ix_sessions_absolute_expires_at", "absolute_expires_at"),
    )

    family_id: Mapped[UUID]
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[bytes] = mapped_column(unique=True)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("sessions.id", ondelete="SET NULL"))
    rotated_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    revoke_reason: Mapped[str | None]
    idle_expires_at: Mapped[datetime]
    absolute_expires_at: Mapped[datetime]
    ip: Mapped[str | None] = mapped_column(INET())
    user_agent: Mapped[str | None]
    device_label: Mapped[str | None]
    last_used_at: Mapped[datetime] = mapped_column(server_default=func.now())
