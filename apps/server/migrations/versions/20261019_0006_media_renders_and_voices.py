from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

MEDIA_PERMISSIONS = (
    ("render.testbed", "Run renders through the admin test bed"),
    ("voices.manage", "Curate the built-in voice catalog"),
    ("music.manage", "Manage the licensed music library"),
)
FIRST_MEDIA_PERMISSION_INDEX = 17
INSERT_ADMIN_MEDIA_PERMISSIONS = (
    "INSERT INTO role_permissions (role_id, permission_id) "
    "SELECT roles.id, permissions.id FROM roles CROSS JOIN permissions "
    "WHERE roles.key = 'admin' AND permissions.key IN ('render.testbed', 'voices.manage', 'music.manage')"
)
DELETE_MEDIA_PERMISSIONS = "DELETE FROM permissions WHERE key IN ('render.testbed', 'voices.manage', 'music.manage')"


def timestamps() -> list[sa.Column[datetime]]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def create_assets() -> None:
    op.create_table(
        "assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("sha256", sa.LargeBinary(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        *timestamps(),
        sa.CheckConstraint(
            "kind IN ('video', 'audio', 'image', 'subtitle', 'thumbnail', 'voice_sample', 'skill_file', 'avatar', "
            "'html')",
            name=op.f("ck_assets_kind"),
        ),
        sa.CheckConstraint("status IN ('pending', 'ready', 'failed')", name=op.f("ck_assets_status")),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_assets_size_bytes_non_negative")),
        sa.CheckConstraint("sha256 IS NULL OR octet_length(sha256) = 32", name=op.f("ck_assets_sha256_length")),
        sa.CheckConstraint("status <> 'ready' OR sha256 IS NOT NULL", name=op.f("ck_assets_ready_has_sha256")),
        sa.CheckConstraint(
            "(width IS NULL OR width > 0) AND (height IS NULL OR height > 0) "
            "AND (duration_ms IS NULL OR duration_ms >= 0)",
            name=op.f("ck_assets_dimensions_positive"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assets")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_assets_storage_key")),
    )
    op.create_index(op.f("ix_assets_owner_user_id_kind_created_at"), "assets", ["owner_user_id", "kind", "created_at"])
    op.create_index(
        op.f("ix_assets_status_created_at"),
        "assets",
        ["status", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def create_renders() -> None:
    op.create_table(
        "renders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column("progress", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column(
            "options", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("composition_asset_id", sa.Uuid(), nullable=False),
        sa.Column("mixed_audio_asset_id", sa.Uuid(), nullable=True),
        sa.Column("subtitles_vtt_asset_id", sa.Uuid(), nullable=True),
        sa.Column("subtitles_srt_asset_id", sa.Uuid(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("validation_report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "stage_timings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "checkpoints",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint("source IN ('testbed', 'job', 'mcp')", name=op.f("ck_renders_source")),
        sa.CheckConstraint(
            "status IN ('queued', 'preparing', 'voicing', 'mixing', 'capturing', 'encoding', 'finalizing', "
            "'completed', 'failed', 'cancelled')",
            name=op.f("ck_renders_status"),
        ),
        sa.CheckConstraint(
            "stage IS NULL OR stage IN ('preparing', 'voicing', 'mixing', 'capturing', 'encoding', 'finalizing')",
            name=op.f("ck_renders_stage"),
        ),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name=op.f("ck_renders_progress_range")),
        sa.CheckConstraint("status <> 'completed' OR progress = 100", name=op.f("ck_renders_completed_progress")),
        sa.CheckConstraint("jsonb_typeof(options) = 'object'", name=op.f("ck_renders_options_object")),
        sa.CheckConstraint("jsonb_typeof(stage_timings) = 'object'", name=op.f("ck_renders_stage_timings_object")),
        sa.CheckConstraint("jsonb_typeof(checkpoints) = 'object'", name=op.f("ck_renders_checkpoints_object")),
        sa.CheckConstraint(
            "validation_report IS NULL OR jsonb_typeof(validation_report) = 'object'",
            name=op.f("ck_renders_validation_report_object"),
        ),
        sa.CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name=op.f("ck_renders_duration_non_negative")),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[a-z][a-z0-9_]{1,59}$'", name=op.f("ck_renders_error_code_format")
        ),
        sa.CheckConstraint(
            "error_message IS NULL OR char_length(error_message) <= 2000", name=op.f("ck_renders_error_message_length")
        ),
        sa.CheckConstraint("status <> 'failed' OR error_code IS NOT NULL", name=op.f("ck_renders_failed_has_error")),
        sa.CheckConstraint(
            "(status IN ('completed', 'failed', 'cancelled')) = (completed_at IS NOT NULL)",
            name=op.f("ck_renders_terminal_has_completed_at"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], name=op.f("fk_renders_owner_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["composition_asset_id"],
            ["assets.id"],
            name=op.f("fk_renders_composition_asset_id_assets"),
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["mixed_audio_asset_id"],
            ["assets.id"],
            name=op.f("fk_renders_mixed_audio_asset_id_assets"),
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["subtitles_vtt_asset_id"],
            ["assets.id"],
            name=op.f("fk_renders_subtitles_vtt_asset_id_assets"),
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["subtitles_srt_asset_id"],
            ["assets.id"],
            name=op.f("fk_renders_subtitles_srt_asset_id_assets"),
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_renders")),
    )
    op.create_index(op.f("ix_renders_owner_user_id_created_at_id"), "renders", ["owner_user_id", "created_at", "id"])
    op.create_index(
        op.f("ix_renders_status_updated_at"),
        "renders",
        ["status", "updated_at"],
        postgresql_where=sa.text("status NOT IN ('completed', 'failed', 'cancelled')"),
    )
    op.create_index(op.f("ix_renders_composition_asset_id"), "renders", ["composition_asset_id"])
    op.create_index(op.f("ix_renders_mixed_audio_asset_id"), "renders", ["mixed_audio_asset_id"])
    op.create_index(op.f("ix_renders_subtitles_vtt_asset_id"), "renders", ["subtitles_vtt_asset_id"])
    op.create_index(op.f("ix_renders_subtitles_srt_asset_id"), "renders", ["subtitles_srt_asset_id"])


def create_renditions() -> None:
    op.create_table(
        "renditions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("render_id", sa.Uuid(), nullable=False),
        sa.Column("aspect", sa.Text(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("poster_webp_asset_id", sa.Uuid(), nullable=True),
        sa.Column("poster_jpeg_asset_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("burned_in_subtitles", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *timestamps(),
        sa.CheckConstraint("aspect IN ('16:9', '9:16', '1:1')", name=op.f("ck_renditions_aspect")),
        sa.CheckConstraint("status IN ('pending', 'rendering', 'ready', 'failed')", name=op.f("ck_renditions_status")),
        sa.CheckConstraint("width > 0 AND height > 0", name=op.f("ck_renditions_dimensions_positive")),
        sa.CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name=op.f("ck_renditions_duration_non_negative")),
        sa.CheckConstraint("status <> 'ready' OR asset_id IS NOT NULL", name=op.f("ck_renditions_ready_has_asset")),
        sa.ForeignKeyConstraint(
            ["render_id"], ["renders.id"], name=op.f("fk_renditions_render_id_renders"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["assets.id"], name=op.f("fk_renditions_asset_id_assets"), ondelete="NO ACTION"
        ),
        sa.ForeignKeyConstraint(
            ["poster_webp_asset_id"],
            ["assets.id"],
            name=op.f("fk_renditions_poster_webp_asset_id_assets"),
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["poster_jpeg_asset_id"],
            ["assets.id"],
            name=op.f("fk_renditions_poster_jpeg_asset_id_assets"),
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_renditions")),
        sa.UniqueConstraint("render_id", "aspect", name=op.f("uq_renditions_render_id_aspect")),
    )
    op.create_index(op.f("ix_renditions_asset_id"), "renditions", ["asset_id"])
    op.create_index(op.f("ix_renditions_poster_webp_asset_id"), "renditions", ["poster_webp_asset_id"])
    op.create_index(op.f("ix_renditions_poster_jpeg_asset_id"), "renditions", ["poster_jpeg_asset_id"])


def create_tts_cache() -> None:
    op.create_table(
        "tts_cache",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("content_hash", sa.LargeBinary(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("provider_voice_id", sa.Text(), nullable=False),
        sa.Column("characters", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("word_timings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("audio_asset_id", sa.Uuid(), nullable=False),
        sa.Column("hit_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        *timestamps(),
        sa.CheckConstraint("octet_length(content_hash) = 32", name=op.f("ck_tts_cache_content_hash_length")),
        sa.CheckConstraint("provider IN ('elevenlabs', 'openai', 'fake')", name=op.f("ck_tts_cache_provider")),
        sa.CheckConstraint(
            "characters >= 0 AND duration_ms > 0 AND hit_count >= 0", name=op.f("ck_tts_cache_counters")
        ),
        sa.CheckConstraint("jsonb_typeof(word_timings) = 'array'", name=op.f("ck_tts_cache_word_timings_array")),
        sa.ForeignKeyConstraint(
            ["audio_asset_id"],
            ["assets.id"],
            name=op.f("fk_tts_cache_audio_asset_id_assets"),
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tts_cache")),
        sa.UniqueConstraint("content_hash", name=op.f("uq_tts_cache_content_hash")),
    )
    op.create_index(op.f("ix_tts_cache_audio_asset_id"), "tts_cache", ["audio_asset_id"])
    op.create_index(op.f("ix_tts_cache_last_used_at"), "tts_cache", ["last_used_at"])
    op.create_index(op.f("ix_tts_cache_provider_provider_voice_id"), "tts_cache", ["provider", "provider_voice_id"])


def create_music_tracks() -> None:
    op.create_table(
        "music_tracks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("audio_asset_id", sa.Uuid(), nullable=False),
        sa.Column("mood", sa.Text(), nullable=False),
        sa.Column("bpm", sa.SmallInteger(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("license_name", sa.Text(), nullable=False),
        sa.Column("license_url", sa.Text(), nullable=False),
        sa.Column("attribution_text", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        *timestamps(),
        sa.CheckConstraint("char_length(title) BETWEEN 1 AND 120", name=op.f("ck_music_tracks_title_length")),
        sa.CheckConstraint("mood ~ '^[a-z][a-z0-9-]{1,39}$'", name=op.f("ck_music_tracks_mood_format")),
        sa.CheckConstraint("bpm IS NULL OR bpm BETWEEN 30 AND 300", name=op.f("ck_music_tracks_bpm_range")),
        sa.CheckConstraint("duration_ms > 0", name=op.f("ck_music_tracks_duration_positive")),
        sa.CheckConstraint(
            r"char_length(license_name) BETWEEN 1 AND 120 AND license_url ~ '^https://[^\s]+$' "
            "AND char_length(license_url) <= 2000",
            name=op.f("ck_music_tracks_license_recorded"),
        ),
        sa.CheckConstraint(
            "attribution_text IS NULL OR char_length(attribution_text) <= 500",
            name=op.f("ck_music_tracks_attribution_length"),
        ),
        sa.ForeignKeyConstraint(
            ["audio_asset_id"],
            ["assets.id"],
            name=op.f("fk_music_tracks_audio_asset_id_assets"),
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_music_tracks_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_music_tracks")),
    )
    op.create_index(op.f("ix_music_tracks_audio_asset_id"), "music_tracks", ["audio_asset_id"])
    op.create_index(op.f("ix_music_tracks_created_by_user_id"), "music_tracks", ["created_by_user_id"])
    op.create_index(op.f("ix_music_tracks_mood"), "music_tracks", ["mood"], postgresql_where=sa.text("is_active"))


def create_voices() -> None:
    op.create_table(
        "voices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_voice_id", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("failure_code", sa.Text(), nullable=True),
        sa.Column("preview_asset_id", sa.Uuid(), nullable=True),
        sa.Column(
            "labels", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        *timestamps(),
        sa.CheckConstraint("kind IN ('builtin', 'cloned')", name=op.f("ck_voices_kind")),
        sa.CheckConstraint("status IN ('pending', 'ready', 'failed', 'disabled')", name=op.f("ck_voices_status")),
        sa.CheckConstraint("provider IN ('elevenlabs', 'openai', 'fake')", name=op.f("ck_voices_provider")),
        sa.CheckConstraint("(kind = 'builtin') = (owner_user_id IS NULL)", name=op.f("ck_voices_ownership")),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 80", name=op.f("ck_voices_name_length")),
        sa.CheckConstraint("language ~ '^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$'", name=op.f("ck_voices_language_format")),
        sa.CheckConstraint("jsonb_typeof(labels) = 'object'", name=op.f("ck_voices_labels_object")),
        sa.CheckConstraint(
            "status <> 'ready' OR provider_voice_id IS NOT NULL", name=op.f("ck_voices_ready_has_provider_voice_id")
        ),
        sa.CheckConstraint(
            "status <> 'failed' OR failure_code IS NOT NULL", name=op.f("ck_voices_failed_has_failure_code")
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[a-z][a-z0-9_]{1,59}$'",
            name=op.f("ck_voices_failure_code_format"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], name=op.f("fk_voices_owner_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["preview_asset_id"], ["assets.id"], name=op.f("fk_voices_preview_asset_id_assets"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_voices")),
        sa.UniqueConstraint("provider", "provider_voice_id", name=op.f("uq_voices_provider_provider_voice_id")),
    )
    op.create_index(op.f("ix_voices_owner_user_id"), "voices", ["owner_user_id"])
    op.create_index(op.f("ix_voices_preview_asset_id"), "voices", ["preview_asset_id"])
    op.create_index(
        op.f("ix_voices_kind_language"),
        "voices",
        ["kind", "language"],
        postgresql_where=sa.text("status = 'ready'"),
    )


def create_voice_consents() -> None:
    op.create_table(
        "voice_consents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("voice_id", sa.Uuid(), nullable=True),
        sa.Column("voice_reference", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("statement_version", sa.Text(), nullable=False),
        sa.Column("statement_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("consent_asset_id", sa.Uuid(), nullable=False),
        sa.Column("challenge_sentence", sa.Text(), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("match_percent", sa.SmallInteger(), nullable=False),
        sa.Column("sample_count", sa.SmallInteger(), nullable=False),
        sa.Column("sample_total_ms", sa.Integer(), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "octet_length(statement_sha256) = 32", name=op.f("ck_voice_consents_statement_sha256_length")
        ),
        sa.CheckConstraint("match_percent BETWEEN 0 AND 100", name=op.f("ck_voice_consents_match_percent_range")),
        sa.CheckConstraint(
            "char_length(challenge_sentence) BETWEEN 1 AND 300 AND char_length(transcript) <= 600",
            name=op.f("ck_voice_consents_text_length"),
        ),
        sa.CheckConstraint(
            "user_agent IS NULL OR char_length(user_agent) <= 512", name=op.f("ck_voice_consents_user_agent_length")
        ),
        sa.CheckConstraint("sample_count >= 1 AND sample_total_ms > 0", name=op.f("ck_voice_consents_samples")),
        sa.ForeignKeyConstraint(
            ["voice_id"], ["voices.id"], name=op.f("fk_voice_consents_voice_id_voices"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_voice_consents_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["consent_asset_id"],
            ["assets.id"],
            name=op.f("fk_voice_consents_consent_asset_id_assets"),
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_voice_consents")),
        sa.UniqueConstraint("voice_id", name=op.f("uq_voice_consents_voice_id")),
        sa.UniqueConstraint("voice_reference", name=op.f("uq_voice_consents_voice_reference")),
    )
    op.create_index(op.f("ix_voice_consents_user_id"), "voice_consents", ["user_id"])
    op.create_index(op.f("ix_voice_consents_consent_asset_id"), "voice_consents", ["consent_asset_id"])


def add_asset_owner_foreign_key_after_every_other_user_reference() -> None:
    op.create_foreign_key(
        op.f("fk_assets_owner_user_id_users"),
        "assets",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="CASCADE",
    )


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
            for index, (key, description) in enumerate(MEDIA_PERMISSIONS, start=FIRST_MEDIA_PERMISSION_INDEX)
        ],
    )
    op.execute(INSERT_ADMIN_MEDIA_PERMISSIONS)


def upgrade() -> None:
    create_assets()
    create_renders()
    create_renditions()
    create_tts_cache()
    create_music_tracks()
    create_voices()
    create_voice_consents()
    add_asset_owner_foreign_key_after_every_other_user_reference()
    op.create_foreign_key(
        op.f("fk_user_preferences_default_voice_id_voices"),
        "user_preferences",
        "voices",
        ["default_voice_id"],
        ["id"],
        ondelete="SET NULL",
    )
    seed_permissions()


def downgrade() -> None:
    op.execute(DELETE_MEDIA_PERMISSIONS)
    op.drop_constraint(op.f("fk_user_preferences_default_voice_id_voices"), "user_preferences", type_="foreignkey")
    op.drop_table("voice_consents")
    op.drop_table("voices")
    op.drop_table("music_tracks")
    op.drop_table("tts_cache")
    op.drop_table("renditions")
    op.drop_table("renders")
    op.drop_table("assets")
