from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import DBAPIError

from motionile.core.config import PSYCOPG_SCHEME, with_driver
from motionile.models import metadata
from motionile.modules.access import PERMISSION_KEYS

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
MEDIA_PERMISSION_KEYS = {"render.testbed", "voices.manage", "music.manage"}
DELETE_ACTIONS = {"a": "NO ACTION", "c": "CASCADE", "n": "SET NULL", "r": "RESTRICT"}

EXPECTED_CONSTRAINTS = {
    "assets": {
        "pk_assets",
        "fk_assets_owner_user_id_users",
        "uq_assets_storage_key",
        "ck_assets_kind",
        "ck_assets_status",
        "ck_assets_size_bytes_non_negative",
        "ck_assets_sha256_length",
        "ck_assets_ready_has_sha256",
        "ck_assets_dimensions_positive",
    },
    "renders": {
        "pk_renders",
        "fk_renders_owner_user_id_users",
        "fk_renders_composition_asset_id_assets",
        "fk_renders_mixed_audio_asset_id_assets",
        "fk_renders_subtitles_vtt_asset_id_assets",
        "fk_renders_subtitles_srt_asset_id_assets",
        "ck_renders_source",
        "ck_renders_status",
        "ck_renders_stage",
        "ck_renders_progress_range",
        "ck_renders_completed_progress",
        "ck_renders_options_object",
        "ck_renders_stage_timings_object",
        "ck_renders_checkpoints_object",
        "ck_renders_validation_report_object",
        "ck_renders_duration_non_negative",
        "ck_renders_error_code_format",
        "ck_renders_error_message_length",
        "ck_renders_failed_has_error",
        "ck_renders_terminal_has_completed_at",
    },
    "renditions": {
        "pk_renditions",
        "fk_renditions_render_id_renders",
        "fk_renditions_asset_id_assets",
        "fk_renditions_poster_webp_asset_id_assets",
        "fk_renditions_poster_jpeg_asset_id_assets",
        "uq_renditions_render_id_aspect",
        "ck_renditions_aspect",
        "ck_renditions_status",
        "ck_renditions_dimensions_positive",
        "ck_renditions_duration_non_negative",
        "ck_renditions_ready_has_asset",
    },
    "tts_cache": {
        "pk_tts_cache",
        "fk_tts_cache_audio_asset_id_assets",
        "uq_tts_cache_content_hash",
        "ck_tts_cache_content_hash_length",
        "ck_tts_cache_provider",
        "ck_tts_cache_counters",
        "ck_tts_cache_word_timings_array",
    },
    "music_tracks": {
        "pk_music_tracks",
        "fk_music_tracks_audio_asset_id_assets",
        "fk_music_tracks_created_by_user_id_users",
        "ck_music_tracks_title_length",
        "ck_music_tracks_mood_format",
        "ck_music_tracks_bpm_range",
        "ck_music_tracks_duration_positive",
        "ck_music_tracks_license_recorded",
        "ck_music_tracks_attribution_length",
    },
    "voices": {
        "pk_voices",
        "fk_voices_owner_user_id_users",
        "fk_voices_preview_asset_id_assets",
        "uq_voices_provider_provider_voice_id",
        "ck_voices_kind",
        "ck_voices_status",
        "ck_voices_provider",
        "ck_voices_ownership",
        "ck_voices_name_length",
        "ck_voices_language_format",
        "ck_voices_labels_object",
        "ck_voices_ready_has_provider_voice_id",
        "ck_voices_failed_has_failure_code",
        "ck_voices_failure_code_format",
    },
    "voice_consents": {
        "pk_voice_consents",
        "fk_voice_consents_voice_id_voices",
        "fk_voice_consents_user_id_users",
        "fk_voice_consents_consent_asset_id_assets",
        "uq_voice_consents_voice_id",
        "uq_voice_consents_voice_reference",
        "ck_voice_consents_statement_sha256_length",
        "ck_voice_consents_match_percent_range",
        "ck_voice_consents_text_length",
        "ck_voice_consents_user_agent_length",
        "ck_voice_consents_samples",
    },
}
EXPECTED_INDEXES = {
    "assets": {"ix_assets_owner_user_id_kind_created_at", "ix_assets_status_created_at"},
    "renders": {
        "ix_renders_owner_user_id_created_at_id",
        "ix_renders_status_updated_at",
        "ix_renders_composition_asset_id",
        "ix_renders_mixed_audio_asset_id",
        "ix_renders_subtitles_vtt_asset_id",
        "ix_renders_subtitles_srt_asset_id",
    },
    "renditions": {
        "ix_renditions_asset_id",
        "ix_renditions_poster_webp_asset_id",
        "ix_renditions_poster_jpeg_asset_id",
    },
    "tts_cache": {
        "ix_tts_cache_audio_asset_id",
        "ix_tts_cache_last_used_at",
        "ix_tts_cache_provider_provider_voice_id",
    },
    "music_tracks": {
        "ix_music_tracks_audio_asset_id",
        "ix_music_tracks_created_by_user_id",
        "ix_music_tracks_mood",
    },
    "voices": {"ix_voices_owner_user_id", "ix_voices_preview_asset_id", "ix_voices_kind_language"},
    "voice_consents": {"ix_voice_consents_user_id", "ix_voice_consents_consent_asset_id"},
    "user_preferences": {"ix_user_preferences_default_voice_id"},
}
EXPECTED_PARTIAL_INDEXES = {
    "ix_assets_status_created_at": "status = 'pending'",
    "ix_renders_status_updated_at": "status <> ALL",
    "ix_music_tracks_mood": "is_active",
    "ix_voices_kind_language": "status = 'ready'",
}
EXPECTED_DELETE_ACTIONS = {
    "fk_assets_owner_user_id_users": "CASCADE",
    "fk_renders_owner_user_id_users": "CASCADE",
    "fk_renders_composition_asset_id_assets": "NO ACTION",
    "fk_renders_mixed_audio_asset_id_assets": "NO ACTION",
    "fk_renders_subtitles_vtt_asset_id_assets": "NO ACTION",
    "fk_renders_subtitles_srt_asset_id_assets": "NO ACTION",
    "fk_renditions_render_id_renders": "CASCADE",
    "fk_renditions_asset_id_assets": "NO ACTION",
    "fk_renditions_poster_webp_asset_id_assets": "NO ACTION",
    "fk_renditions_poster_jpeg_asset_id_assets": "NO ACTION",
    "fk_tts_cache_audio_asset_id_assets": "NO ACTION",
    "fk_music_tracks_audio_asset_id_assets": "NO ACTION",
    "fk_music_tracks_created_by_user_id_users": "SET NULL",
    "fk_voices_owner_user_id_users": "CASCADE",
    "fk_voices_preview_asset_id_assets": "SET NULL",
    "fk_voice_consents_voice_id_voices": "SET NULL",
    "fk_voice_consents_user_id_users": "CASCADE",
    "fk_voice_consents_consent_asset_id_assets": "NO ACTION",
    "fk_user_preferences_default_voice_id_voices": "SET NULL",
}


@pytest.fixture
def connection(migrated_database_url: str) -> Iterator[Connection]:
    engine = create_engine(with_driver(migrated_database_url, PSYCOPG_SCHEME))
    with engine.connect() as opened:
        transaction = opened.begin()
        yield opened
        transaction.rollback()
    engine.dispose()


@contextmanager
def rejected(connection: Connection, match: str) -> Generator[None]:
    with pytest.raises(DBAPIError, match=match), connection.begin_nested():
        yield


def token() -> str:
    return uuid4().hex


def digest(label: str = "") -> bytes:
    return sha256(f"{label}{token()}".encode()).digest()


def insert(connection: Connection, table: str, **values: Any) -> UUID:
    result = connection.execute(sa.insert(metadata.tables[table]).values(**values))
    primary_key = result.inserted_primary_key
    assert primary_key is not None
    return UUID(str(primary_key[0]))


def update(connection: Connection, table: str, key: UUID, **values: Any) -> None:
    target = metadata.tables[table]
    primary_key = next(iter(target.primary_key.columns))
    connection.execute(sa.update(target).where(primary_key == key).values(**values))


def count(connection: Connection, table: str, key: UUID) -> int:
    target = metadata.tables[table]
    primary_key = next(iter(target.primary_key.columns))
    return connection.execute(sa.select(sa.func.count()).select_from(target).where(primary_key == key)).scalar_one()


def column_value(connection: Connection, table: str, key: UUID, column: str) -> Any:
    target = metadata.tables[table]
    primary_key = next(iter(target.primary_key.columns))
    return connection.execute(sa.select(target.c[column]).where(primary_key == key)).scalar_one()


def delete_user(connection: Connection, user_id: UUID) -> None:
    connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


def make_user(connection: Connection) -> UUID:
    return insert(connection, "users")


def make_asset(connection: Connection, owner_user_id: UUID | None = None, **overrides: Any) -> UUID:
    values: dict[str, Any] = {
        "owner_user_id": owner_user_id,
        "kind": "video",
        "storage_key": f"media/u/test/{token()}.mp4",
        "content_type": "video/mp4",
    }
    return insert(connection, "assets", **{**values, **overrides})


def make_ready_asset(connection: Connection, owner_user_id: UUID | None = None, **overrides: Any) -> UUID:
    return make_asset(connection, owner_user_id, status="ready", sha256=digest(), size_bytes=10, **overrides)


def make_render(
    connection: Connection, user_id: UUID, composition_asset_id: UUID | None = None, **overrides: Any
) -> UUID:
    values: dict[str, Any] = {
        "owner_user_id": user_id,
        "source": "testbed",
        "composition_asset_id": composition_asset_id or make_asset(connection, user_id, kind="html"),
    }
    return insert(connection, "renders", **{**values, **overrides})


def make_rendition(connection: Connection, render_id: UUID, **overrides: Any) -> UUID:
    values: dict[str, Any] = {"render_id": render_id, "aspect": "16:9", "width": 1920, "height": 1080}
    return insert(connection, "renditions", **{**values, **overrides})


def make_cache_entry(connection: Connection, audio_asset_id: UUID | None = None, **overrides: Any) -> UUID:
    values: dict[str, Any] = {
        "content_hash": digest(),
        "provider": "elevenlabs",
        "model": "eleven_multilingual_v2",
        "provider_voice_id": f"voice_{token()[:12]}",
        "characters": 120,
        "duration_ms": 4_000,
        "word_timings": [{"text": "Hello", "startMs": 0, "endMs": 400}],
        "audio_asset_id": audio_asset_id or make_asset(connection, kind="audio", storage_key=f"tts/{token()}.mp3"),
        "last_used_at": NOW,
    }
    return insert(connection, "tts_cache", **{**values, **overrides})


def make_track(connection: Connection, audio_asset_id: UUID | None = None, **overrides: Any) -> UUID:
    values: dict[str, Any] = {
        "title": "Morning light",
        "audio_asset_id": audio_asset_id or make_asset(connection, kind="audio", storage_key=f"music/{token()}.m4a"),
        "mood": "calm",
        "duration_ms": 90_000,
        "license_name": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
    }
    return insert(connection, "music_tracks", **{**values, **overrides})


def make_builtin_voice(connection: Connection, **overrides: Any) -> UUID:
    values: dict[str, Any] = {
        "provider": "elevenlabs",
        "provider_voice_id": f"voice_{token()[:12]}",
        "name": "Rachel",
        "kind": "builtin",
        "language": "en",
    }
    return insert(connection, "voices", **{**values, **overrides})


def make_cloned_voice(connection: Connection, owner_user_id: UUID, **overrides: Any) -> UUID:
    values: dict[str, Any] = {
        "owner_user_id": owner_user_id,
        "provider": "elevenlabs",
        "name": "My voice",
        "kind": "cloned",
        "language": "en-IN",
    }
    return insert(connection, "voices", **{**values, **overrides})


def make_consent(
    connection: Connection, user_id: UUID, voice_id: UUID | None, consent_asset_id: UUID | None = None, **overrides: Any
) -> UUID:
    values: dict[str, Any] = {
        "voice_id": voice_id,
        "voice_reference": voice_id or uuid4(),
        "user_id": user_id,
        "statement_version": "2026-10-19",
        "statement_sha256": digest(),
        "accepted_at": NOW,
        "ip": "203.0.113.7",
        "user_agent": "Mozilla/5.0",
        "consent_asset_id": consent_asset_id or make_asset(connection, user_id, kind="voice_sample"),
        "challenge_sentence": "Motionile blue seven river 42",
        "transcript": "motionile blue seven river 42",
        "match_percent": 96,
        "sample_count": 2,
        "sample_total_ms": 45_000,
    }
    return insert(connection, "voice_consents", **{**values, **overrides})


def constraint_names(connection: Connection, table: str) -> set[str]:
    query = text("SELECT conname FROM pg_constraint WHERE conrelid = CAST(:table AS regclass)")
    return set(connection.execute(query, {"table": table}).scalars())


def index_names(connection: Connection, table: str) -> set[str]:
    query = text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = :table")
    return {name for name in connection.execute(query, {"table": table}).scalars() if name.startswith("ix_")}


def index_definition(connection: Connection, name: str) -> str:
    query = text("SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' AND indexname = :name")
    return connection.execute(query, {"name": name}).scalar_one()


def delete_actions(connection: Connection) -> dict[str, str]:
    query = text("SELECT conname, confdeltype FROM pg_constraint WHERE contype = 'f'")
    return {name: DELETE_ACTIONS[action] for name, action in connection.execute(query).all()}


@pytest.mark.parametrize("table", sorted(EXPECTED_CONSTRAINTS))
def test_every_constraint_of_the_media_tables_exists_with_its_documented_name(
    connection: Connection, table: str
) -> None:
    assert constraint_names(connection, table) == EXPECTED_CONSTRAINTS[table]


@pytest.mark.parametrize("table", sorted(EXPECTED_INDEXES))
def test_every_index_of_the_media_tables_exists_with_its_documented_name(connection: Connection, table: str) -> None:
    assert index_names(connection, table) == EXPECTED_INDEXES[table]


@pytest.mark.parametrize(("name", "predicate"), sorted(EXPECTED_PARTIAL_INDEXES.items()))
def test_partial_indexes_carry_their_predicates(connection: Connection, name: str, predicate: str) -> None:
    assert predicate in index_definition(connection, name)


def test_every_foreign_key_chooses_its_delete_action_explicitly(connection: Connection) -> None:
    actions = delete_actions(connection)

    assert {name: actions[name] for name in EXPECTED_DELETE_ACTIONS} == EXPECTED_DELETE_ACTIONS


def test_the_media_models_agree_with_the_migrated_columns(connection: Connection) -> None:
    for table in EXPECTED_CONSTRAINTS:
        query = text(
            "SELECT column_name, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table"
        )
        migrated = {name: nullable == "YES" for name, nullable in connection.execute(query, {"table": table}).all()}
        modelled = {column.name: bool(column.nullable) for column in metadata.tables[table].columns}

        assert migrated == modelled


def test_assets_accept_system_and_owned_rows(connection: Connection) -> None:
    owned = make_asset(connection, make_user(connection))
    system = make_asset(connection, None, kind="audio", storage_key=f"voice-preview/{token()}.mp3")

    assert column_value(connection, "assets", owned, "status") == "pending"
    assert column_value(connection, "assets", owned, "size_bytes") == 0
    assert column_value(connection, "assets", owned, "metadata") == {}
    assert column_value(connection, "assets", system, "owner_user_id") is None


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"kind": "document"}, "ck_assets_kind"),
        ({"status": "uploading"}, "ck_assets_status"),
        ({"size_bytes": -1}, "ck_assets_size_bytes_non_negative"),
        ({"sha256": b"short"}, "ck_assets_sha256_length"),
        ({"status": "ready"}, "ck_assets_ready_has_sha256"),
        ({"width": 0}, "ck_assets_dimensions_positive"),
        ({"height": -5}, "ck_assets_dimensions_positive"),
        ({"duration_ms": -1}, "ck_assets_dimensions_positive"),
    ],
)
def test_asset_checks(connection: Connection, overrides: dict[str, Any], constraint: str) -> None:
    with rejected(connection, constraint):
        make_asset(connection, **overrides)


@pytest.mark.parametrize(
    "kind", ["video", "audio", "image", "subtitle", "thumbnail", "voice_sample", "skill_file", "avatar", "html"]
)
def test_assets_accept_every_documented_kind(connection: Connection, kind: str) -> None:
    make_asset(connection, kind=kind)


def test_a_ready_asset_has_a_sha256_and_zero_durations_are_allowed(connection: Connection) -> None:
    make_ready_asset(connection, width=1920, height=1080, duration_ms=0)

    with rejected(connection, "ck_assets_ready_has_sha256"):
        make_asset(connection, status="ready")


def test_asset_storage_keys_are_unique(connection: Connection) -> None:
    make_asset(connection, storage_key="media/u/test/shared.mp4")

    with rejected(connection, "uq_assets_storage_key"):
        make_asset(connection, storage_key="media/u/test/shared.mp4")


def test_deleting_a_user_deletes_their_assets(connection: Connection) -> None:
    user_id = make_user(connection)
    asset_id = make_asset(connection, user_id)
    system_id = make_asset(connection)

    delete_user(connection, user_id)

    assert count(connection, "assets", asset_id) == 0
    assert count(connection, "assets", system_id) == 1


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"source": "cron"}, "ck_renders_source"),
        ({"status": "running"}, "ck_renders_status"),
        ({"stage": "uploading"}, "ck_renders_stage"),
        ({"stage": "queued"}, "ck_renders_stage"),
        ({"progress": -1}, "ck_renders_progress_range"),
        ({"progress": 101}, "ck_renders_progress_range"),
        ({"options": []}, "ck_renders_options_object"),
        ({"stage_timings": []}, "ck_renders_stage_timings_object"),
        ({"checkpoints": "text"}, "ck_renders_checkpoints_object"),
        ({"validation_report": []}, "ck_renders_validation_report_object"),
        ({"duration_ms": -1}, "ck_renders_duration_non_negative"),
        ({"error_code": "Timeout"}, "ck_renders_error_code_format"),
        ({"error_code": "t"}, "ck_renders_error_code_format"),
        ({"error_code": "a" * 61}, "ck_renders_error_code_format"),
        ({"error_message": "m" * 2001}, "ck_renders_error_message_length"),
    ],
)
def test_render_value_checks(connection: Connection, overrides: dict[str, Any], constraint: str) -> None:
    with rejected(connection, constraint):
        make_render(connection, make_user(connection), **overrides)


def test_a_new_render_starts_queued_with_empty_documents(connection: Connection) -> None:
    render_id = make_render(connection, make_user(connection))

    assert column_value(connection, "renders", render_id, "status") == "queued"
    assert column_value(connection, "renders", render_id, "progress") == 0
    assert column_value(connection, "renders", render_id, "stage") is None
    assert column_value(connection, "renders", render_id, "options") == {}
    assert column_value(connection, "renders", render_id, "stage_timings") == {}
    assert column_value(connection, "renders", render_id, "checkpoints") == {}
    assert column_value(connection, "renders", render_id, "validation_report") is None


@pytest.mark.parametrize("source", ["testbed", "job", "mcp"])
def test_renders_accept_every_documented_source(connection: Connection, source: str) -> None:
    make_render(connection, make_user(connection), source=source)


@pytest.mark.parametrize("stage", ["preparing", "voicing", "mixing", "capturing", "encoding", "finalizing"])
def test_renders_accept_every_documented_stage(connection: Connection, stage: str) -> None:
    make_render(connection, make_user(connection), status=stage, stage=stage, progress=10)


def test_a_failed_render_keeps_the_stage_where_it_stopped(connection: Connection) -> None:
    render_id = make_render(
        connection,
        make_user(connection),
        status="failed",
        stage="capturing",
        error_code="network_violation",
        error_message="The composition requested an external resource",
        completed_at=NOW,
        validation_report={"issues": []},
    )

    assert column_value(connection, "renders", render_id, "stage") == "capturing"


def test_a_completed_render_reports_full_progress(connection: Connection) -> None:
    user_id = make_user(connection)

    with rejected(connection, "ck_renders_completed_progress"):
        make_render(connection, user_id, status="completed", progress=99, completed_at=NOW)
    make_render(connection, user_id, status="completed", progress=100, completed_at=NOW)


def test_a_failed_render_names_its_error(connection: Connection) -> None:
    user_id = make_user(connection)

    with rejected(connection, "ck_renders_failed_has_error"):
        make_render(connection, user_id, status="failed", completed_at=NOW)
    make_render(connection, user_id, status="failed", completed_at=NOW, error_code="timeout")


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_terminal_renders_need_a_completion_time(connection: Connection, status: str) -> None:
    user_id = make_user(connection)
    overrides: dict[str, Any] = {"status": status, "progress": 100, "error_code": "timeout"}

    with rejected(connection, "ck_renders_terminal_has_completed_at"):
        make_render(connection, user_id, **overrides)
    make_render(connection, user_id, completed_at=NOW, **overrides)


@pytest.mark.parametrize("status", ["queued", "preparing", "voicing", "mixing", "capturing", "encoding", "finalizing"])
def test_running_renders_have_no_completion_time(connection: Connection, status: str) -> None:
    with rejected(connection, "ck_renders_terminal_has_completed_at"):
        make_render(connection, make_user(connection), status=status, completed_at=NOW)


def test_a_render_is_moved_through_its_states_by_updates(connection: Connection) -> None:
    render_id = make_render(connection, make_user(connection))

    update(connection, "renders", render_id, status="preparing", stage="preparing", started_at=NOW)
    update(connection, "renders", render_id, status="cancelled", completed_at=NOW)
    with rejected(connection, "ck_renders_terminal_has_completed_at"):
        update(connection, "renders", render_id, completed_at=None)


def test_a_render_needs_a_composition_asset(connection: Connection) -> None:
    with rejected(connection, "composition_asset_id"):
        insert(connection, "renders", owner_user_id=make_user(connection), source="testbed")


def test_a_render_references_its_output_assets(connection: Connection) -> None:
    user_id = make_user(connection)

    render_id = make_render(
        connection,
        user_id,
        mixed_audio_asset_id=make_asset(connection, user_id, kind="audio"),
        subtitles_vtt_asset_id=make_asset(connection, user_id, kind="subtitle"),
        subtitles_srt_asset_id=make_asset(connection, user_id, kind="subtitle"),
    )

    assert column_value(connection, "renders", render_id, "mixed_audio_asset_id") is not None


@pytest.mark.parametrize(
    "column", ["composition_asset_id", "mixed_audio_asset_id", "subtitles_vtt_asset_id", "subtitles_srt_asset_id"]
)
def test_an_asset_used_by_a_render_cannot_be_deleted_on_its_own(connection: Connection, column: str) -> None:
    user_id = make_user(connection)
    asset_id = make_asset(connection, user_id, kind="html")
    make_render(connection, user_id, **{"composition_asset_id": make_asset(connection, user_id), column: asset_id})

    with rejected(connection, "violates foreign key constraint"):
        connection.execute(text("DELETE FROM assets WHERE id = :id"), {"id": asset_id})


def test_deleting_a_user_deletes_renders_and_their_assets_in_one_statement(connection: Connection) -> None:
    user_id = make_user(connection)
    composition = make_asset(connection, user_id, kind="html")
    audio = make_asset(connection, user_id, kind="audio")
    render_id = make_render(connection, user_id, composition, mixed_audio_asset_id=audio)
    rendition_id = make_rendition(connection, render_id, asset_id=make_ready_asset(connection, user_id))

    delete_user(connection, user_id)

    for table, key in (
        ("renders", render_id),
        ("renditions", rendition_id),
        ("assets", composition),
        ("assets", audio),
    ):
        assert count(connection, table, key) == 0


def test_another_users_renders_survive_a_deletion(connection: Connection) -> None:
    user_id = make_user(connection)
    other_id = make_user(connection)
    make_render(connection, user_id)
    survivor = make_render(connection, other_id)

    delete_user(connection, user_id)

    assert count(connection, "renders", survivor) == 1


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"aspect": "4:3"}, "ck_renditions_aspect"),
        ({"aspect": "16x9"}, "ck_renditions_aspect"),
        ({"status": "done"}, "ck_renditions_status"),
        ({"width": 0}, "ck_renditions_dimensions_positive"),
        ({"height": -1}, "ck_renditions_dimensions_positive"),
        ({"duration_ms": -1}, "ck_renditions_duration_non_negative"),
        ({"status": "ready"}, "ck_renditions_ready_has_asset"),
    ],
)
def test_rendition_checks(connection: Connection, overrides: dict[str, Any], constraint: str) -> None:
    render_id = make_render(connection, make_user(connection))

    with rejected(connection, constraint):
        make_rendition(connection, render_id, **overrides)


def test_a_ready_rendition_has_its_video_and_optional_posters(connection: Connection) -> None:
    user_id = make_user(connection)
    render_id = make_render(connection, user_id)

    rendition_id = make_rendition(
        connection,
        render_id,
        status="ready",
        asset_id=make_ready_asset(connection, user_id),
        poster_webp_asset_id=make_ready_asset(connection, user_id, kind="thumbnail"),
        poster_jpeg_asset_id=make_ready_asset(connection, user_id, kind="thumbnail"),
        duration_ms=61_000,
        burned_in_subtitles=True,
    )

    assert column_value(connection, "renditions", rendition_id, "burned_in_subtitles") is True


def test_a_pending_rendition_defaults(connection: Connection) -> None:
    rendition_id = make_rendition(connection, make_render(connection, make_user(connection)))

    assert column_value(connection, "renditions", rendition_id, "status") == "pending"
    assert column_value(connection, "renditions", rendition_id, "burned_in_subtitles") is False
    assert column_value(connection, "renditions", rendition_id, "asset_id") is None


def test_a_render_has_one_rendition_per_aspect(connection: Connection) -> None:
    render_id = make_render(connection, make_user(connection))
    make_rendition(connection, render_id, aspect="16:9")

    with rejected(connection, "uq_renditions_render_id_aspect"):
        make_rendition(connection, render_id, aspect="16:9")
    make_rendition(connection, render_id, aspect="9:16", width=1080, height=1920)
    make_rendition(connection, render_id, aspect="1:1", width=1080, height=1080)
    make_rendition(connection, make_render(connection, make_user(connection)), aspect="16:9")


def test_deleting_a_render_deletes_its_renditions(connection: Connection) -> None:
    render_id = make_render(connection, make_user(connection))
    rendition_id = make_rendition(connection, render_id)

    connection.execute(text("DELETE FROM renders WHERE id = :id"), {"id": render_id})

    assert count(connection, "renditions", rendition_id) == 0


@pytest.mark.parametrize("column", ["asset_id", "poster_webp_asset_id", "poster_jpeg_asset_id"])
def test_an_asset_used_by_a_rendition_cannot_be_deleted_on_its_own(connection: Connection, column: str) -> None:
    user_id = make_user(connection)
    asset_id = make_ready_asset(connection, user_id)
    render_id = make_render(connection, user_id)
    make_rendition(connection, render_id, **{column: asset_id})

    with rejected(connection, "violates foreign key constraint"):
        connection.execute(text("DELETE FROM assets WHERE id = :id"), {"id": asset_id})


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"content_hash": b"short"}, "ck_tts_cache_content_hash_length"),
        ({"content_hash": b"x" * 33}, "ck_tts_cache_content_hash_length"),
        ({"provider": "azure"}, "ck_tts_cache_provider"),
        ({"characters": -1}, "ck_tts_cache_counters"),
        ({"duration_ms": 0}, "ck_tts_cache_counters"),
        ({"hit_count": -1}, "ck_tts_cache_counters"),
        ({"word_timings": {}}, "ck_tts_cache_word_timings_array"),
    ],
)
def test_tts_cache_checks(connection: Connection, overrides: dict[str, Any], constraint: str) -> None:
    with rejected(connection, constraint):
        make_cache_entry(connection, **overrides)


@pytest.mark.parametrize("provider", ["elevenlabs", "openai", "fake"])
def test_tts_cache_accepts_every_documented_provider(connection: Connection, provider: str) -> None:
    entry_id = make_cache_entry(connection, provider=provider)

    assert column_value(connection, "tts_cache", entry_id, "hit_count") == 0


def test_tts_cache_entries_are_unique_per_content_hash(connection: Connection) -> None:
    shared = digest("shared")
    make_cache_entry(connection, content_hash=shared)

    with rejected(connection, "uq_tts_cache_content_hash"):
        make_cache_entry(connection, content_hash=shared)


def test_the_audio_of_a_cache_entry_cannot_be_deleted_before_the_entry(connection: Connection) -> None:
    audio_id = make_asset(connection, kind="audio", storage_key=f"tts/{token()}.mp3")
    entry_id = make_cache_entry(connection, audio_id)

    with rejected(connection, "violates foreign key constraint"):
        connection.execute(text("DELETE FROM assets WHERE id = :id"), {"id": audio_id})
    connection.execute(text("DELETE FROM tts_cache WHERE id = :id"), {"id": entry_id})
    connection.execute(text("DELETE FROM assets WHERE id = :id"), {"id": audio_id})

    assert count(connection, "assets", audio_id) == 0


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"title": ""}, "ck_music_tracks_title_length"),
        ({"title": "t" * 121}, "ck_music_tracks_title_length"),
        ({"mood": "Calm"}, "ck_music_tracks_mood_format"),
        ({"mood": "c"}, "ck_music_tracks_mood_format"),
        ({"mood": "very calm"}, "ck_music_tracks_mood_format"),
        ({"bpm": 29}, "ck_music_tracks_bpm_range"),
        ({"bpm": 301}, "ck_music_tracks_bpm_range"),
        ({"duration_ms": 0}, "ck_music_tracks_duration_positive"),
        ({"license_name": ""}, "ck_music_tracks_license_recorded"),
        ({"license_name": "l" * 121}, "ck_music_tracks_license_recorded"),
        ({"license_url": "http://example.com/license"}, "ck_music_tracks_license_recorded"),
        ({"license_url": "https://example.com/has space"}, "ck_music_tracks_license_recorded"),
        ({"license_url": "https://"}, "ck_music_tracks_license_recorded"),
        ({"license_url": "https://example.com/" + "p" * 2000}, "ck_music_tracks_license_recorded"),
        ({"attribution_text": "a" * 501}, "ck_music_tracks_attribution_length"),
    ],
)
def test_music_track_checks(connection: Connection, overrides: dict[str, Any], constraint: str) -> None:
    with rejected(connection, constraint):
        make_track(connection, **overrides)


def test_a_music_track_needs_a_license_name_and_url(connection: Connection) -> None:
    with rejected(connection, "license_name"):
        make_track(connection, license_name=None)
    with rejected(connection, "license_url"):
        make_track(connection, license_url=None)


def test_a_new_track_is_inactive_and_accepts_boundary_values(connection: Connection) -> None:
    track_id = make_track(connection, bpm=30, attribution_text="a" * 500, mood="lo-fi", title="t" * 120)

    assert column_value(connection, "music_tracks", track_id, "is_active") is False
    make_track(connection, bpm=300)
    make_track(connection, bpm=None)


def test_the_audio_of_a_track_cannot_be_deleted_while_the_track_exists(connection: Connection) -> None:
    audio_id = make_asset(connection, kind="audio", storage_key=f"music/{token()}.m4a")
    make_track(connection, audio_id)

    with rejected(connection, "violates foreign key constraint"):
        connection.execute(text("DELETE FROM assets WHERE id = :id"), {"id": audio_id})


def test_deleting_the_uploader_keeps_the_track(connection: Connection) -> None:
    admin_id = make_user(connection)
    track_id = make_track(connection, created_by_user_id=admin_id)

    delete_user(connection, admin_id)

    assert count(connection, "music_tracks", track_id) == 1
    assert column_value(connection, "music_tracks", track_id, "created_by_user_id") is None


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"kind": "stock"}, "ck_voices_kind"),
        ({"status": "archived"}, "ck_voices_status"),
        ({"provider": "azure"}, "ck_voices_provider"),
        ({"name": ""}, "ck_voices_name_length"),
        ({"name": "n" * 81}, "ck_voices_name_length"),
        ({"language": "EN"}, "ck_voices_language_format"),
        ({"language": "en_IN"}, "ck_voices_language_format"),
        ({"language": "e"}, "ck_voices_language_format"),
        ({"labels": []}, "ck_voices_labels_object"),
        ({"failure_code": "Consent"}, "ck_voices_failure_code_format"),
        ({"failure_code": "c"}, "ck_voices_failure_code_format"),
    ],
)
def test_voice_checks(connection: Connection, overrides: dict[str, Any], constraint: str) -> None:
    with rejected(connection, constraint):
        make_builtin_voice(connection, **overrides)


@pytest.mark.parametrize("language", ["en", "hi", "en-IN", "hi-IN", "zh-Hans-CN", "fil", "es-419"])
def test_voices_accept_bcp47_languages(connection: Connection, language: str) -> None:
    make_builtin_voice(connection, language=language)


def test_builtin_voices_have_no_owner_and_cloned_voices_have_one(connection: Connection) -> None:
    user_id = make_user(connection)

    with rejected(connection, "ck_voices_ownership"):
        make_builtin_voice(connection, owner_user_id=user_id)
    with rejected(connection, "ck_voices_ownership"):
        insert(connection, "voices", provider="elevenlabs", name="Orphan", kind="cloned", language="en")
    make_builtin_voice(connection)
    make_cloned_voice(connection, user_id)


def test_a_cloned_voice_is_pending_without_a_provider_voice_until_it_is_ready(connection: Connection) -> None:
    user_id = make_user(connection)

    voice_id = make_cloned_voice(connection, user_id)

    assert column_value(connection, "voices", voice_id, "status") == "pending"
    assert column_value(connection, "voices", voice_id, "provider_voice_id") is None
    assert column_value(connection, "voices", voice_id, "labels") == {}
    with rejected(connection, "ck_voices_ready_has_provider_voice_id"):
        update(connection, "voices", voice_id, status="ready")
    update(connection, "voices", voice_id, status="ready", provider_voice_id="provider-voice-1")


def test_a_failed_voice_names_its_failure(connection: Connection) -> None:
    user_id = make_user(connection)

    with rejected(connection, "ck_voices_failed_has_failure_code"):
        make_cloned_voice(connection, user_id, status="failed")
    make_cloned_voice(connection, user_id, status="failed", failure_code="consent_mismatch")


@pytest.mark.parametrize("status", ["pending", "ready", "failed", "disabled"])
def test_voices_accept_every_documented_status(connection: Connection, status: str) -> None:
    make_builtin_voice(connection, status=status, failure_code="provider_failed" if status == "failed" else None)


def test_a_synchronized_builtin_voice_can_start_disabled(connection: Connection) -> None:
    voice_id = make_builtin_voice(connection, status="disabled")

    update(connection, "voices", voice_id, status="ready", labels={"accent": "british"})

    assert column_value(connection, "voices", voice_id, "labels") == {"accent": "british"}


def test_provider_voice_ids_are_unique_per_provider_and_nulls_never_collide(connection: Connection) -> None:
    user_id = make_user(connection)
    make_builtin_voice(connection, provider="elevenlabs", provider_voice_id="shared")

    with rejected(connection, "uq_voices_provider_provider_voice_id"):
        make_builtin_voice(connection, provider="elevenlabs", provider_voice_id="shared")
    make_builtin_voice(connection, provider="openai", provider_voice_id="shared")
    make_cloned_voice(connection, user_id)
    make_cloned_voice(connection, user_id)


def test_deleting_a_user_deletes_their_cloned_voices_only(connection: Connection) -> None:
    user_id = make_user(connection)
    cloned = make_cloned_voice(connection, user_id)
    builtin = make_builtin_voice(connection)

    delete_user(connection, user_id)

    assert count(connection, "voices", cloned) == 0
    assert count(connection, "voices", builtin) == 1


def test_deleting_a_preview_asset_clears_the_voice_link(connection: Connection) -> None:
    preview_id = make_asset(connection, kind="audio", storage_key=f"voice-preview/{token()}.mp3")
    voice_id = make_builtin_voice(connection, preview_asset_id=preview_id)

    connection.execute(text("DELETE FROM assets WHERE id = :id"), {"id": preview_id})

    assert column_value(connection, "voices", voice_id, "preview_asset_id") is None


def test_deleting_a_voice_clears_the_default_voice_of_preferences(connection: Connection) -> None:
    user_id = make_user(connection)
    voice_id = make_cloned_voice(connection, user_id)
    insert(connection, "user_preferences", user_id=user_id, default_voice_id=voice_id)

    connection.execute(text("DELETE FROM voices WHERE id = :id"), {"id": voice_id})

    assert column_value(connection, "user_preferences", user_id, "default_voice_id") is None


def test_the_default_voice_of_preferences_must_exist(connection: Connection) -> None:
    with rejected(connection, "fk_user_preferences_default_voice_id_voices"):
        insert(connection, "user_preferences", user_id=make_user(connection), default_voice_id=uuid4())


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"statement_sha256": b"short"}, "ck_voice_consents_statement_sha256_length"),
        ({"match_percent": -1}, "ck_voice_consents_match_percent_range"),
        ({"match_percent": 101}, "ck_voice_consents_match_percent_range"),
        ({"challenge_sentence": ""}, "ck_voice_consents_text_length"),
        ({"challenge_sentence": "s" * 301}, "ck_voice_consents_text_length"),
        ({"transcript": "t" * 601}, "ck_voice_consents_text_length"),
        ({"user_agent": "u" * 513}, "ck_voice_consents_user_agent_length"),
        ({"sample_count": 0}, "ck_voice_consents_samples"),
        ({"sample_total_ms": 0}, "ck_voice_consents_samples"),
    ],
)
def test_voice_consent_checks(connection: Connection, overrides: dict[str, Any], constraint: str) -> None:
    user_id = make_user(connection)
    voice_id = make_cloned_voice(connection, user_id)

    with rejected(connection, constraint):
        make_consent(connection, user_id, voice_id, **overrides)


def test_a_consent_records_the_evidence_with_optional_network_details(connection: Connection) -> None:
    user_id = make_user(connection)
    voice_id = make_cloned_voice(connection, user_id)

    consent_id = make_consent(connection, user_id, voice_id, ip=None, user_agent=None, transcript="", match_percent=0)

    assert column_value(connection, "voice_consents", consent_id, "ip") is None
    assert column_value(connection, "voice_consents", consent_id, "voice_reference") == voice_id


def test_a_voice_has_one_consent_and_a_reference_is_never_reused(connection: Connection) -> None:
    user_id = make_user(connection)
    voice_id = make_cloned_voice(connection, user_id)
    make_consent(connection, user_id, voice_id)

    with rejected(connection, "uq_voice_consents_voice_id"):
        make_consent(connection, user_id, voice_id, voice_reference=uuid4())
    with rejected(connection, "uq_voice_consents_voice_reference"):
        make_consent(connection, user_id, None, voice_reference=voice_id)


def test_a_consent_needs_an_existing_recording(connection: Connection) -> None:
    user_id = make_user(connection)
    voice_id = make_cloned_voice(connection, user_id)

    with rejected(connection, "fk_voice_consents_consent_asset_id_assets"):
        make_consent(connection, user_id, voice_id, consent_asset_id=uuid4())


def test_the_consent_evidence_outlives_the_voice(connection: Connection) -> None:
    user_id = make_user(connection)
    voice_id = make_cloned_voice(connection, user_id)
    consent_id = make_consent(connection, user_id, voice_id)

    connection.execute(text("DELETE FROM voices WHERE id = :id"), {"id": voice_id})

    assert count(connection, "voice_consents", consent_id) == 1
    assert column_value(connection, "voice_consents", consent_id, "voice_id") is None
    assert column_value(connection, "voice_consents", consent_id, "voice_reference") == voice_id


def test_evidence_of_several_deleted_voices_can_coexist(connection: Connection) -> None:
    user_id = make_user(connection)
    first = make_cloned_voice(connection, user_id)
    second = make_cloned_voice(connection, user_id)
    make_consent(connection, user_id, first)
    make_consent(connection, user_id, second)

    connection.execute(text("DELETE FROM voices WHERE id IN (:first, :second)"), {"first": first, "second": second})

    remaining = connection.execute(
        text("SELECT count(*) FROM voice_consents WHERE user_id = :id AND voice_id IS NULL"), {"id": user_id}
    ).scalar_one()
    assert remaining == 2


def test_the_recording_of_a_consent_cannot_be_deleted_on_its_own(connection: Connection) -> None:
    user_id = make_user(connection)
    recording = make_asset(connection, user_id, kind="voice_sample")
    make_consent(connection, user_id, make_cloned_voice(connection, user_id), recording)

    with rejected(connection, "violates foreign key constraint"):
        connection.execute(text("DELETE FROM assets WHERE id = :id"), {"id": recording})


def test_deleting_a_user_removes_every_trace_of_their_media_in_one_statement(connection: Connection) -> None:
    user_id = make_user(connection)
    system_audio = make_asset(connection, kind="audio", storage_key=f"tts/{token()}.mp3")
    cache_entry = make_cache_entry(connection, system_audio)
    track = make_track(connection, created_by_user_id=user_id)
    composition = make_asset(connection, user_id, kind="html")
    mixed_audio = make_asset(connection, user_id, kind="audio")
    subtitles = make_asset(connection, user_id, kind="subtitle")
    video = make_ready_asset(connection, user_id)
    poster = make_ready_asset(connection, user_id, kind="thumbnail")
    render_id = make_render(
        connection, user_id, composition, mixed_audio_asset_id=mixed_audio, subtitles_vtt_asset_id=subtitles
    )
    rendition_id = make_rendition(connection, render_id, asset_id=video, poster_webp_asset_id=poster, status="ready")
    preview = make_asset(connection, user_id, kind="audio")
    voice_id = make_cloned_voice(connection, user_id, preview_asset_id=preview)
    consent_id = make_consent(connection, user_id, voice_id)
    consent_asset = column_value(connection, "voice_consents", consent_id, "consent_asset_id")
    insert(connection, "user_preferences", user_id=user_id, default_voice_id=voice_id)

    delete_user(connection, user_id)

    owned = (
        ("renders", render_id),
        ("renditions", rendition_id),
        ("voices", voice_id),
        ("voice_consents", consent_id),
        ("assets", composition),
        ("assets", mixed_audio),
        ("assets", subtitles),
        ("assets", video),
        ("assets", poster),
        ("assets", preview),
        ("assets", consent_asset),
        ("user_preferences", user_id),
    )
    for table, key in owned:
        assert count(connection, table, key) == 0, table
    assert count(connection, "tts_cache", cache_entry) == 1
    assert count(connection, "assets", system_audio) == 1
    assert count(connection, "music_tracks", track) == 1
    assert column_value(connection, "music_tracks", track, "created_by_user_id") is None


def test_permission_catalog_matches_the_database(connection: Connection) -> None:
    keys = set(connection.execute(text("SELECT key FROM permissions")).scalars())

    assert keys == PERMISSION_KEYS
    assert keys >= MEDIA_PERMISSION_KEYS


def test_admin_holds_the_media_permissions_and_ordinary_users_do_not(connection: Connection) -> None:
    query = text(
        "SELECT permissions.key FROM role_permissions "
        "JOIN roles ON roles.id = role_permissions.role_id "
        "JOIN permissions ON permissions.id = role_permissions.permission_id "
        "WHERE roles.key = :role AND permissions.key IN ('render.testbed', 'voices.manage', 'music.manage')"
    )

    admin = set(connection.execute(query, {"role": "admin"}).scalars())
    user = set(connection.execute(query, {"role": "user"}).scalars())

    assert admin == MEDIA_PERMISSION_KEYS
    assert user == set()
