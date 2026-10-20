from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, SmallInteger, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from motionile.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Voice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "voices"
    __table_args__ = (
        UniqueConstraint("provider", "provider_voice_id", name="uq_voices_provider_provider_voice_id"),
        CheckConstraint("kind IN ('builtin', 'cloned')", name="kind"),
        CheckConstraint("status IN ('pending', 'ready', 'failed', 'disabled')", name="status"),
        CheckConstraint("provider IN ('elevenlabs', 'openai', 'fake')", name="provider"),
        CheckConstraint("(kind = 'builtin') = (owner_user_id IS NULL)", name="ownership"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="name_length"),
        CheckConstraint("language ~ '^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$'", name="language_format"),
        CheckConstraint("jsonb_typeof(labels) = 'object'", name="labels_object"),
        CheckConstraint("status <> 'ready' OR provider_voice_id IS NOT NULL", name="ready_has_provider_voice_id"),
        CheckConstraint("status <> 'failed' OR failure_code IS NOT NULL", name="failed_has_failure_code"),
        CheckConstraint("failure_code IS NULL OR failure_code ~ '^[a-z][a-z0-9_]{1,59}$'", name="failure_code_format"),
        Index("ix_voices_owner_user_id", "owner_user_id"),
        Index("ix_voices_preview_asset_id", "preview_asset_id"),
        Index("ix_voices_kind_language", "kind", "language", postgresql_where=text("status = 'ready'")),
    )

    owner_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str]
    provider_voice_id: Mapped[str | None]
    name: Mapped[str]
    kind: Mapped[str]
    language: Mapped[str]
    status: Mapped[str] = mapped_column(server_default=text("'pending'"))
    failure_code: Mapped[str | None]
    preview_asset_id: Mapped[UUID | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"))
    labels: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class VoiceConsent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "voice_consents"
    __table_args__ = (
        UniqueConstraint("voice_id", name="uq_voice_consents_voice_id"),
        UniqueConstraint("voice_reference", name="uq_voice_consents_voice_reference"),
        CheckConstraint("octet_length(statement_sha256) = 32", name="statement_sha256_length"),
        CheckConstraint("match_percent BETWEEN 0 AND 100", name="match_percent_range"),
        CheckConstraint(
            "char_length(challenge_sentence) BETWEEN 1 AND 300 AND char_length(transcript) <= 600", name="text_length"
        ),
        CheckConstraint("user_agent IS NULL OR char_length(user_agent) <= 512", name="user_agent_length"),
        CheckConstraint("sample_count >= 1 AND sample_total_ms > 0", name="samples"),
        Index("ix_voice_consents_user_id", "user_id"),
        Index("ix_voice_consents_consent_asset_id", "consent_asset_id"),
    )

    voice_id: Mapped[UUID | None] = mapped_column(ForeignKey("voices.id", ondelete="SET NULL"))
    voice_reference: Mapped[UUID]
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    statement_version: Mapped[str]
    statement_sha256: Mapped[bytes]
    accepted_at: Mapped[datetime]
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None]
    consent_asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id", ondelete="NO ACTION"))
    challenge_sentence: Mapped[str]
    transcript: Mapped[str]
    match_percent: Mapped[int] = mapped_column(SmallInteger)
    sample_count: Mapped[int] = mapped_column(SmallInteger)
    sample_total_ms: Mapped[int]
