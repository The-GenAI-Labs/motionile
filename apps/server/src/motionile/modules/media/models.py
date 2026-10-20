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

from motionile.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Asset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("storage_key", name="uq_assets_storage_key"),
        CheckConstraint(
            "kind IN ('video', 'audio', 'image', 'subtitle', 'thumbnail', 'voice_sample', 'skill_file', 'avatar', "
            "'html')",
            name="kind",
        ),
        CheckConstraint("status IN ('pending', 'ready', 'failed')", name="status"),
        CheckConstraint("size_bytes >= 0", name="size_bytes_non_negative"),
        CheckConstraint("sha256 IS NULL OR octet_length(sha256) = 32", name="sha256_length"),
        CheckConstraint("status <> 'ready' OR sha256 IS NOT NULL", name="ready_has_sha256"),
        CheckConstraint(
            "(width IS NULL OR width > 0) AND (height IS NULL OR height > 0) "
            "AND (duration_ms IS NULL OR duration_ms >= 0)",
            name="dimensions_positive",
        ),
        Index("ix_assets_owner_user_id_kind_created_at", "owner_user_id", "kind", "created_at"),
        Index("ix_assets_status_created_at", "status", "created_at", postgresql_where=text("status = 'pending'")),
    )

    owner_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str]
    storage_key: Mapped[str]
    content_type: Mapped[str]
    size_bytes: Mapped[int] = mapped_column(BigInteger, server_default="0")
    sha256: Mapped[bytes | None]
    duration_ms: Mapped[int | None]
    width: Mapped[int | None]
    height: Mapped[int | None]
    status: Mapped[str] = mapped_column(server_default=text("'pending'"))
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))


class Render(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "renders"
    __table_args__ = (
        CheckConstraint("source IN ('testbed', 'job', 'mcp')", name="source"),
        CheckConstraint(
            "status IN ('queued', 'preparing', 'voicing', 'mixing', 'capturing', 'encoding', 'finalizing', "
            "'completed', 'failed', 'cancelled')",
            name="status",
        ),
        CheckConstraint(
            "stage IS NULL OR stage IN ('preparing', 'voicing', 'mixing', 'capturing', 'encoding', 'finalizing')",
            name="stage",
        ),
        CheckConstraint("progress BETWEEN 0 AND 100", name="progress_range"),
        CheckConstraint("status <> 'completed' OR progress = 100", name="completed_progress"),
        CheckConstraint("jsonb_typeof(options) = 'object'", name="options_object"),
        CheckConstraint("jsonb_typeof(stage_timings) = 'object'", name="stage_timings_object"),
        CheckConstraint("jsonb_typeof(checkpoints) = 'object'", name="checkpoints_object"),
        CheckConstraint(
            "validation_report IS NULL OR jsonb_typeof(validation_report) = 'object'", name="validation_report_object"
        ),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="duration_non_negative"),
        CheckConstraint("error_code IS NULL OR error_code ~ '^[a-z][a-z0-9_]{1,59}$'", name="error_code_format"),
        CheckConstraint("error_message IS NULL OR char_length(error_message) <= 2000", name="error_message_length"),
        CheckConstraint("status <> 'failed' OR error_code IS NOT NULL", name="failed_has_error"),
        CheckConstraint(
            "(status IN ('completed', 'failed', 'cancelled')) = (completed_at IS NOT NULL)",
            name="terminal_has_completed_at",
        ),
        Index("ix_renders_owner_user_id_created_at_id", "owner_user_id", "created_at", "id"),
        Index(
            "ix_renders_status_updated_at",
            "status",
            "updated_at",
            postgresql_where=text("status NOT IN ('completed', 'failed', 'cancelled')"),
        ),
        Index("ix_renders_composition_asset_id", "composition_asset_id"),
        Index("ix_renders_mixed_audio_asset_id", "mixed_audio_asset_id"),
        Index("ix_renders_subtitles_vtt_asset_id", "subtitles_vtt_asset_id"),
        Index("ix_renders_subtitles_srt_asset_id", "subtitles_srt_asset_id"),
    )

    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source: Mapped[str]
    status: Mapped[str] = mapped_column(server_default=text("'queued'"))
    stage: Mapped[str | None]
    progress: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    composition_asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id", ondelete="NO ACTION"))
    mixed_audio_asset_id: Mapped[UUID | None] = mapped_column(ForeignKey("assets.id", ondelete="NO ACTION"))
    subtitles_vtt_asset_id: Mapped[UUID | None] = mapped_column(ForeignKey("assets.id", ondelete="NO ACTION"))
    subtitles_srt_asset_id: Mapped[UUID | None] = mapped_column(ForeignKey("assets.id", ondelete="NO ACTION"))
    duration_ms: Mapped[int | None]
    validation_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    stage_timings: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    checkpoints: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    error_code: Mapped[str | None]
    error_message: Mapped[str | None]
    cancel_requested_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]


class Rendition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "renditions"
    __table_args__ = (
        UniqueConstraint("render_id", "aspect", name="uq_renditions_render_id_aspect"),
        CheckConstraint("aspect IN ('16:9', '9:16', '1:1')", name="aspect"),
        CheckConstraint("status IN ('pending', 'rendering', 'ready', 'failed')", name="status"),
        CheckConstraint("width > 0 AND height > 0", name="dimensions_positive"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="duration_non_negative"),
        CheckConstraint("status <> 'ready' OR asset_id IS NOT NULL", name="ready_has_asset"),
        Index("ix_renditions_asset_id", "asset_id"),
        Index("ix_renditions_poster_webp_asset_id", "poster_webp_asset_id"),
        Index("ix_renditions_poster_jpeg_asset_id", "poster_jpeg_asset_id"),
    )

    render_id: Mapped[UUID] = mapped_column(ForeignKey("renders.id", ondelete="CASCADE"))
    aspect: Mapped[str]
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    asset_id: Mapped[UUID | None] = mapped_column(ForeignKey("assets.id", ondelete="NO ACTION"))
    poster_webp_asset_id: Mapped[UUID | None] = mapped_column(ForeignKey("assets.id", ondelete="NO ACTION"))
    poster_jpeg_asset_id: Mapped[UUID | None] = mapped_column(ForeignKey("assets.id", ondelete="NO ACTION"))
    status: Mapped[str] = mapped_column(server_default=text("'pending'"))
    duration_ms: Mapped[int | None]
    burned_in_subtitles: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class TtsCacheEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tts_cache"
    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_tts_cache_content_hash"),
        CheckConstraint("octet_length(content_hash) = 32", name="content_hash_length"),
        CheckConstraint("provider IN ('elevenlabs', 'openai', 'fake')", name="provider"),
        CheckConstraint("characters >= 0 AND duration_ms > 0 AND hit_count >= 0", name="counters"),
        CheckConstraint("jsonb_typeof(word_timings) = 'array'", name="word_timings_array"),
        Index("ix_tts_cache_audio_asset_id", "audio_asset_id"),
        Index("ix_tts_cache_last_used_at", "last_used_at"),
        Index("ix_tts_cache_provider_provider_voice_id", "provider", "provider_voice_id"),
    )

    content_hash: Mapped[bytes]
    provider: Mapped[str]
    model: Mapped[str]
    provider_voice_id: Mapped[str]
    characters: Mapped[int]
    duration_ms: Mapped[int]
    word_timings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    audio_asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id", ondelete="NO ACTION"))
    hit_count: Mapped[int] = mapped_column(BigInteger, server_default="0")
    last_used_at: Mapped[datetime]


class MusicTrack(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "music_tracks"
    __table_args__ = (
        CheckConstraint("char_length(title) BETWEEN 1 AND 120", name="title_length"),
        CheckConstraint("mood ~ '^[a-z][a-z0-9-]{1,39}$'", name="mood_format"),
        CheckConstraint("bpm IS NULL OR bpm BETWEEN 30 AND 300", name="bpm_range"),
        CheckConstraint("duration_ms > 0", name="duration_positive"),
        CheckConstraint(
            r"char_length(license_name) BETWEEN 1 AND 120 AND license_url ~ '^https://[^\s]+$' "
            "AND char_length(license_url) <= 2000",
            name="license_recorded",
        ),
        CheckConstraint("attribution_text IS NULL OR char_length(attribution_text) <= 500", name="attribution_length"),
        Index("ix_music_tracks_audio_asset_id", "audio_asset_id"),
        Index("ix_music_tracks_created_by_user_id", "created_by_user_id"),
        Index("ix_music_tracks_mood", "mood", postgresql_where=text("is_active")),
    )

    title: Mapped[str]
    audio_asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id", ondelete="NO ACTION"))
    mood: Mapped[str]
    bpm: Mapped[int | None] = mapped_column(SmallInteger)
    duration_ms: Mapped[int]
    license_name: Mapped[str]
    license_url: Mapped[str]
    attribution_text: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
