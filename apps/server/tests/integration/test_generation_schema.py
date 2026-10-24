from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Connection, create_engine, text
from tests.integration.test_media_schema import (
    column_value,
    constraint_names,
    count,
    delete_actions,
    delete_user,
    digest,
    index_definition,
    index_names,
    insert,
    make_asset,
    make_ready_asset,
    make_render,
    make_rendition,
    make_user,
    rejected,
    token,
    update,
)

from motionile.core.config import PSYCOPG_SCHEME, with_driver
from motionile.models import metadata
from motionile.modules.access import PERMISSION_KEYS
from motionile.modules.skills import EMBEDDING_DIMENSIONS

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
GENERATION_PERMISSION_KEYS = {"prompts.manage", "skills.manage", "jobs.read_all", "evals.run"}
ADMIN_GENERATION_KEYS = {"jobs.read_all", "skills.manage"}

EXPECTED_CONSTRAINTS = {
    "jobs": {
        "pk_jobs",
        "fk_jobs_user_id_users",
        "fk_jobs_topic_id_topics",
        "fk_jobs_parent_job_id_jobs",
        "fk_jobs_render_id_renders",
        "uq_jobs_user_id_idempotency_key",
        "ck_jobs_source",
        "ck_jobs_status",
        "ck_jobs_query_length",
        "ck_jobs_options_object",
        "ck_jobs_reports_object",
        "ck_jobs_credits_non_negative",
        "ck_jobs_terminal_has_completed_at",
        "ck_jobs_failed_has_error",
        "ck_jobs_error_code_format",
        "ck_jobs_error_message_length",
        "ck_jobs_not_own_parent",
    },
    "storyboards": {
        "pk_storyboards",
        "fk_storyboards_job_id_jobs",
        "fk_storyboards_approved_by_users",
        "uq_storyboards_job_id_version",
        "ck_storyboards_version_positive",
        "ck_storyboards_origin",
        "ck_storyboards_content_object",
        "ck_storyboards_approval_consistent",
    },
    "scenes": {
        "pk_scenes",
        "fk_scenes_storyboard_id_storyboards",
        "fk_scenes_audio_asset_id_assets",
        "fk_scenes_html_asset_id_assets",
        "uq_scenes_storyboard_id_position",
        "uq_scenes_storyboard_id_scene_key",
        "ck_scenes_scene_key_format",
        "ck_scenes_position_non_negative",
        "ck_scenes_target_duration_ms_range",
        "ck_scenes_actual_duration_ms_non_negative",
        "ck_scenes_status",
        "ck_scenes_repair_attempts_range",
        "ck_scenes_word_timestamps_array",
        "ck_scenes_module_object",
        "ck_scenes_attempt_log_array",
        "ck_scenes_error_code_format",
        "ck_scenes_narration_length",
        "ck_scenes_visual_brief_length",
    },
    "job_events": {
        "pk_job_events",
        "fk_job_events_job_id_jobs",
        "ck_job_events_type_format",
        "ck_job_events_payload_object",
    },
    "share_links": {
        "pk_share_links",
        "fk_share_links_job_id_jobs",
        "fk_share_links_rendition_id_renditions",
        "uq_share_links_slug",
        "ck_share_links_slug_format",
        "ck_share_links_view_count_non_negative",
    },
    "prompt_templates": {
        "pk_prompt_templates",
        "uq_prompt_templates_key",
        "fk_prompt_templates_active_version_id_prompt_versions",
        "ck_prompt_templates_key_format",
    },
    "prompt_versions": {
        "pk_prompt_versions",
        "fk_prompt_versions_template_id_prompt_templates",
        "fk_prompt_versions_created_by_users",
        "uq_prompt_versions_template_id_version",
        "uq_prompt_versions_template_id_checksum",
        "ck_prompt_versions_eval_status",
        "ck_prompt_versions_version_positive",
        "ck_prompt_versions_checksum_length",
        "ck_prompt_versions_variables_array",
        "ck_prompt_versions_eval_report_object",
        "ck_prompt_versions_canary_length",
    },
    "eval_runs": {
        "pk_eval_runs",
        "fk_eval_runs_created_by_users",
        "ck_eval_runs_status",
        "ck_eval_runs_trigger",
        "ck_eval_runs_suite_format",
        "ck_eval_runs_dataset_version_format",
        "ck_eval_runs_prompt_version_ids_size",
        "ck_eval_runs_model_configuration_object",
        "ck_eval_runs_scores_object",
        "ck_eval_runs_finished_consistent",
        "ck_eval_runs_passed_consistent",
        "ck_eval_runs_errored_has_error",
        "ck_eval_runs_error_code_format",
    },
    "skills": {
        "pk_skills",
        "fk_skills_owner_user_id_users",
        "fk_skills_current_version_id_skill_versions",
        "ck_skills_visibility",
        "ck_skills_status",
        "ck_skills_ownership",
        "ck_skills_slug_format",
        "ck_skills_name_length",
        "ck_skills_description_length",
    },
    "skill_versions": {
        "pk_skill_versions",
        "fk_skill_versions_skill_id_skills",
        "fk_skill_versions_created_by_users",
        "uq_skill_versions_skill_id_version",
        "ck_skill_versions_scan_status",
        "ck_skill_versions_version_positive",
        "ck_skill_versions_checksum_length",
        "ck_skill_versions_frontmatter_object",
        "ck_skill_versions_body_md_length",
        "ck_skill_versions_scanned_consistent",
    },
    "skill_files": {
        "pk_skill_files",
        "fk_skill_files_skill_version_id_skill_versions",
        "fk_skill_files_asset_id_assets",
        "uq_skill_files_skill_version_id_path",
        "ck_skill_files_path_safe",
        "ck_skill_files_size_bytes_non_negative",
        "ck_skill_files_sha256_length",
    },
    "skill_embeddings": {
        "pk_skill_embeddings",
        "fk_skill_embeddings_skill_version_id_skill_versions",
    },
}
EXPECTED_INDEXES = {
    "jobs": {
        "ix_jobs_user_id_created_at_id",
        "ix_jobs_user_id_active",
        "ix_jobs_status_updated_at",
        "ix_jobs_topic_id",
        "ix_jobs_parent_job_id",
        "ix_jobs_render_id",
    },
    "storyboards": {"ix_storyboards_approved_by"},
    "scenes": {"ix_scenes_audio_asset_id", "ix_scenes_html_asset_id"},
    "job_events": {"ix_job_events_job_id_id", "ix_job_events_created_at"},
    "share_links": {"ix_share_links_job_id", "ix_share_links_rendition_id"},
    "prompt_templates": {"ix_prompt_templates_active_version_id"},
    "prompt_versions": {"ix_prompt_versions_created_by"},
    "eval_runs": {"ix_eval_runs_suite_created_at", "ix_eval_runs_created_by", "ix_eval_runs_prompt_version_ids"},
    "skills": {
        "ix_skills_owner_user_id_slug",
        "ix_skills_owner_user_id_created_at",
        "ix_skills_owner_user_id",
        "ix_skills_current_version_id",
    },
    "skill_versions": {"ix_skill_versions_created_by", "ix_skill_versions_scan_status_created_at"},
    "skill_files": {"ix_skill_files_asset_id"},
    "skill_embeddings": {"ix_skill_embeddings_embedding"},
}
EXPECTED_PARTIAL_INDEXES = {
    "ix_jobs_user_id_active": "status <> ALL",
    "ix_jobs_status_updated_at": "status <> ALL",
    "ix_skills_owner_user_id_slug": "deleted_at IS NULL",
    "ix_skills_owner_user_id_created_at": "deleted_at IS NULL",
    "ix_skill_versions_scan_status_created_at": "scan_status = 'pending'",
}
EXPECTED_DELETE_ACTIONS = {
    "fk_jobs_user_id_users": "CASCADE",
    "fk_jobs_topic_id_topics": "SET NULL",
    "fk_jobs_parent_job_id_jobs": "SET NULL",
    "fk_jobs_render_id_renders": "SET NULL",
    "fk_storyboards_job_id_jobs": "CASCADE",
    "fk_storyboards_approved_by_users": "SET NULL",
    "fk_scenes_storyboard_id_storyboards": "CASCADE",
    "fk_scenes_audio_asset_id_assets": "SET NULL",
    "fk_scenes_html_asset_id_assets": "SET NULL",
    "fk_job_events_job_id_jobs": "CASCADE",
    "fk_share_links_job_id_jobs": "CASCADE",
    "fk_share_links_rendition_id_renditions": "CASCADE",
    "fk_prompt_templates_active_version_id_prompt_versions": "RESTRICT",
    "fk_prompt_versions_template_id_prompt_templates": "CASCADE",
    "fk_prompt_versions_created_by_users": "SET NULL",
    "fk_eval_runs_created_by_users": "SET NULL",
    "fk_skills_owner_user_id_users": "CASCADE",
    "fk_skills_current_version_id_skill_versions": "SET NULL",
    "fk_skill_versions_skill_id_skills": "CASCADE",
    "fk_skill_versions_created_by_users": "SET NULL",
    "fk_skill_files_skill_version_id_skill_versions": "CASCADE",
    "fk_skill_files_asset_id_assets": "NO ACTION",
    "fk_skill_embeddings_skill_version_id_skill_versions": "CASCADE",
    "fk_usage_records_job_id_jobs": "SET NULL",
}
DEFERRED_FOREIGN_KEYS = {
    "fk_prompt_templates_active_version_id_prompt_versions",
    "fk_skills_current_version_id_skill_versions",
}


@pytest.fixture
def connection(migrated_database_url: str) -> Iterator[Connection]:
    engine = create_engine(with_driver(migrated_database_url, PSYCOPG_SCHEME))
    with engine.connect() as opened:
        transaction = opened.begin()
        yield opened
        transaction.rollback()
    engine.dispose()


def vector_of(first: float) -> list[float]:
    return [first, *([0.0] * (EMBEDDING_DIMENSIONS - 1))]


def make_topic(connection: Connection) -> UUID:
    category = insert(connection, "categories", level="category", slug=token(), name="Science")
    subcategory = insert(
        connection, "categories", level="subcategory", slug=token(), name="Biology", parent_id=category
    )
    return insert(connection, "topics", category_id=subcategory, slug=token(), title="Photosynthesis")


def make_job(connection: Connection, user_id: UUID, **overrides: Any) -> UUID:
    values: dict[str, Any] = {"user_id": user_id, "source": "query", "query": "How do vaccines work?"}
    return insert(connection, "jobs", **{**values, **overrides})


def make_storyboard(connection: Connection, job_id: UUID, **overrides: Any) -> UUID:
    values: dict[str, Any] = {"job_id": job_id, "version": 1, "content": {"title": "Vaccines"}}
    return insert(connection, "storyboards", **{**values, **overrides})


def make_scene(connection: Connection, storyboard_id: UUID, **overrides: Any) -> UUID:
    values: dict[str, Any] = {
        "storyboard_id": storyboard_id,
        "scene_key": "intro",
        "position": 0,
        "narration": "Vaccines teach the immune system.",
        "visual_brief": "A cell meets a harmless virus.",
        "target_duration_ms": 6_000,
    }
    return insert(connection, "scenes", **{**values, **overrides})


def make_event(connection: Connection, job_id: UUID, **overrides: Any) -> UUID:
    values: dict[str, Any] = {"job_id": job_id, "type": "stage.started", "stage": "planning"}
    return insert(connection, "job_events", **{**values, **overrides})


def make_share_link(connection: Connection, job_id: UUID, rendition_id: UUID, **overrides: Any) -> UUID:
    values: dict[str, Any] = {"job_id": job_id, "rendition_id": rendition_id, "slug": token()[:20]}
    return insert(connection, "share_links", **{**values, **overrides})


def make_template(connection: Connection, **overrides: Any) -> UUID:
    values: dict[str, Any] = {"key": f"planner.t{token()[:8]}"}
    return insert(connection, "prompt_templates", **{**values, **overrides})


def make_prompt_version(connection: Connection, template_id: UUID, **overrides: Any) -> UUID:
    values: dict[str, Any] = {
        "template_id": template_id,
        "version": 1,
        "body": "You plan storyboards.",
        "checksum": digest(),
        "canary": "canary-" + token()[:12],
    }
    return insert(connection, "prompt_versions", **{**values, **overrides})


def make_eval_run(connection: Connection, **overrides: Any) -> UUID:
    values: dict[str, Any] = {"suite": "planner", "dataset_version": "2026-10", "trigger": "ci"}
    return insert(connection, "eval_runs", **{**values, **overrides})


def make_finished_run(connection: Connection, **overrides: Any) -> UUID:
    return make_eval_run(connection, status="finished", passed=True, finished_at=NOW, **overrides)


def make_system_skill(connection: Connection, **overrides: Any) -> UUID:
    values: dict[str, Any] = {
        "slug": f"style-{token()[:8]}",
        "name": "Clean",
        "description": "A calm explainer style.",
        "visibility": "system",
    }
    return insert(connection, "skills", **{**values, **overrides})


def make_private_skill(connection: Connection, owner_user_id: UUID, **overrides: Any) -> UUID:
    values: dict[str, Any] = {
        "owner_user_id": owner_user_id,
        "slug": f"mine-{token()[:8]}",
        "name": "Mine",
        "description": "My own skill.",
        "visibility": "private",
    }
    return insert(connection, "skills", **{**values, **overrides})


def make_skill_version(connection: Connection, skill_id: UUID, **overrides: Any) -> UUID:
    values: dict[str, Any] = {
        "skill_id": skill_id,
        "version": 1,
        "body_md": "# Style",
        "frontmatter": {"name": "clean"},
        "checksum": digest(),
    }
    return insert(connection, "skill_versions", **{**values, **overrides})


def make_skill_file(connection: Connection, skill_version_id: UUID, **overrides: Any) -> UUID:
    values: dict[str, Any] = {
        "skill_version_id": skill_version_id,
        "path": "assets/tokens.json",
        "asset_id": make_asset(connection, kind="skill_file", storage_key=f"skills/{token()}.json"),
        "content_type": "application/json",
        "size_bytes": 12,
        "sha256": digest(),
    }
    return insert(connection, "skill_files", **{**values, **overrides})


def make_usage_record(connection: Connection, user_id: UUID, job_id: UUID | None) -> UUID:
    return insert(
        connection,
        "usage_records",
        user_id=user_id,
        job_id=job_id,
        stage="plan",
        provider="anthropic",
        idempotency_key=token(),
    )


@pytest.mark.parametrize("table", sorted(EXPECTED_CONSTRAINTS))
def test_every_constraint_of_the_generation_tables_exists_with_its_documented_name(
    connection: Connection, table: str
) -> None:
    assert constraint_names(connection, table) == EXPECTED_CONSTRAINTS[table]


@pytest.mark.parametrize("table", sorted(EXPECTED_INDEXES))
def test_every_index_of_the_generation_tables_exists_with_its_documented_name(
    connection: Connection, table: str
) -> None:
    assert index_names(connection, table) == EXPECTED_INDEXES[table]


@pytest.mark.parametrize(("name", "predicate"), sorted(EXPECTED_PARTIAL_INDEXES.items()))
def test_partial_indexes_carry_their_predicates(connection: Connection, name: str, predicate: str) -> None:
    assert predicate in index_definition(connection, name)


def test_every_foreign_key_chooses_its_delete_action_explicitly(connection: Connection) -> None:
    actions = delete_actions(connection)

    assert {name: actions[name] for name in EXPECTED_DELETE_ACTIONS} == EXPECTED_DELETE_ACTIONS


def test_the_circular_foreign_keys_are_deferrable_and_initially_deferred(connection: Connection) -> None:
    query = text("SELECT conname FROM pg_constraint WHERE contype = 'f' AND condeferrable AND condeferred")

    assert set(connection.execute(query).scalars()) >= DEFERRED_FOREIGN_KEYS


def test_the_generation_models_agree_with_the_migrated_columns(connection: Connection) -> None:
    for table in EXPECTED_CONSTRAINTS:
        query = text(
            "SELECT column_name, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table"
        )
        migrated = {name: nullable == "YES" for name, nullable in connection.execute(query, {"table": table}).all()}
        modelled = {column.name: bool(column.nullable) for column in metadata.tables[table].columns}

        assert migrated == modelled


def test_a_new_job_starts_queued_with_empty_documents_and_no_credits(connection: Connection) -> None:
    job_id = make_job(connection, make_user(connection))

    assert column_value(connection, "jobs", job_id, "status") == "queued"
    assert column_value(connection, "jobs", job_id, "options") == {}
    assert column_value(connection, "jobs", job_id, "reports") == {}
    assert column_value(connection, "jobs", job_id, "credits_estimated") == 0
    assert column_value(connection, "jobs", job_id, "credits_reserved") == 0
    assert column_value(connection, "jobs", job_id, "credits_charged") is None
    assert column_value(connection, "jobs", job_id, "parent_job_id") is None


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"source": "email"}, "ck_jobs_source"),
        ({"status": "running"}, "ck_jobs_status"),
        ({"query": ""}, "ck_jobs_query_length"),
        ({"query": "q" * 2001}, "ck_jobs_query_length"),
        ({"options": []}, "ck_jobs_options_object"),
        ({"reports": []}, "ck_jobs_reports_object"),
        ({"credits_estimated": -1}, "ck_jobs_credits_non_negative"),
        ({"credits_reserved": -1}, "ck_jobs_credits_non_negative"),
        ({"credits_charged": -1}, "ck_jobs_credits_non_negative"),
        ({"error_code": "Policy"}, "ck_jobs_error_code_format"),
        ({"error_code": "p"}, "ck_jobs_error_code_format"),
        ({"error_message": "m" * 2001}, "ck_jobs_error_message_length"),
    ],
)
def test_job_value_checks(connection: Connection, overrides: dict[str, Any], constraint: str) -> None:
    with rejected(connection, constraint):
        make_job(connection, make_user(connection), **overrides)


def test_a_job_needs_a_query(connection: Connection) -> None:
    with rejected(connection, "query"):
        insert(connection, "jobs", user_id=make_user(connection), source="query")


@pytest.mark.parametrize("source", ["catalog", "query", "mcp"])
def test_jobs_accept_every_documented_source(connection: Connection, source: str) -> None:
    make_job(connection, make_user(connection), source=source)


@pytest.mark.parametrize(
    "status",
    ["queued", "planning", "awaiting_approval", "voicing", "generating", "validating", "rendering"],
)
def test_running_jobs_have_no_completion_time(connection: Connection, status: str) -> None:
    user_id = make_user(connection)

    make_job(connection, user_id, status=status)
    with rejected(connection, "ck_jobs_terminal_has_completed_at"):
        make_job(connection, user_id, status=status, completed_at=NOW)


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_terminal_jobs_need_a_completion_time(connection: Connection, status: str) -> None:
    user_id = make_user(connection)
    overrides: dict[str, Any] = {"status": status, "error_code": "render_failed"}

    with rejected(connection, "ck_jobs_terminal_has_completed_at"):
        make_job(connection, user_id, **overrides)
    make_job(connection, user_id, completed_at=NOW, **overrides)


def test_a_failed_job_names_its_error(connection: Connection) -> None:
    user_id = make_user(connection)

    with rejected(connection, "ck_jobs_failed_has_error"):
        make_job(connection, user_id, status="failed", completed_at=NOW)
    make_job(connection, user_id, status="failed", completed_at=NOW, error_code="model_output_invalid")


def test_a_job_is_moved_through_its_states_by_updates(connection: Connection) -> None:
    job_id = make_job(connection, make_user(connection))

    update(connection, "jobs", job_id, status="planning", current_stage="guard", started_at=NOW)
    update(connection, "jobs", job_id, status="cancelled", completed_at=NOW, cancel_requested_at=NOW)
    with rejected(connection, "ck_jobs_terminal_has_completed_at"):
        update(connection, "jobs", job_id, completed_at=None)


def test_a_job_cannot_be_its_own_parent(connection: Connection) -> None:
    job_id = make_job(connection, make_user(connection))

    with rejected(connection, "ck_jobs_not_own_parent"):
        update(connection, "jobs", job_id, parent_job_id=job_id)


def test_deleting_the_original_keeps_its_revision(connection: Connection) -> None:
    user_id = make_user(connection)
    original = make_job(connection, user_id)
    revision = make_job(connection, user_id, parent_job_id=original)

    connection.execute(text("DELETE FROM jobs WHERE id = :id"), {"id": original})

    assert count(connection, "jobs", revision) == 1
    assert column_value(connection, "jobs", revision, "parent_job_id") is None


def test_a_revision_must_point_at_an_existing_job(connection: Connection) -> None:
    with rejected(connection, "fk_jobs_parent_job_id_jobs"):
        make_job(connection, make_user(connection), parent_job_id=uuid4())


def test_idempotency_keys_are_unique_per_user_and_missing_keys_never_collide(connection: Connection) -> None:
    user_id = make_user(connection)
    make_job(connection, user_id, idempotency_key="key-1")

    with rejected(connection, "uq_jobs_user_id_idempotency_key"):
        make_job(connection, user_id, idempotency_key="key-1")
    make_job(connection, make_user(connection), idempotency_key="key-1")
    make_job(connection, user_id)
    make_job(connection, user_id)


def test_deleting_a_topic_keeps_the_job_and_its_query(connection: Connection) -> None:
    topic_id = make_topic(connection)
    job_id = make_job(connection, make_user(connection), source="catalog", topic_id=topic_id)

    connection.execute(text("DELETE FROM topics WHERE id = :id"), {"id": topic_id})

    assert column_value(connection, "jobs", job_id, "topic_id") is None
    assert column_value(connection, "jobs", job_id, "query") == "How do vaccines work?"


def test_deleting_a_render_clears_the_job_link(connection: Connection) -> None:
    user_id = make_user(connection)
    render_id = make_render(connection, user_id)
    job_id = make_job(connection, user_id, render_id=render_id)

    connection.execute(text("DELETE FROM renders WHERE id = :id"), {"id": render_id})

    assert column_value(connection, "jobs", job_id, "render_id") is None


def test_the_job_must_reference_an_existing_user_topic_and_render(connection: Connection) -> None:
    user_id = make_user(connection)

    with rejected(connection, "fk_jobs_user_id_users"):
        make_job(connection, uuid4())
    with rejected(connection, "fk_jobs_topic_id_topics"):
        make_job(connection, user_id, topic_id=uuid4())
    with rejected(connection, "fk_jobs_render_id_renders"):
        make_job(connection, user_id, render_id=uuid4())


def test_deleting_a_user_removes_every_trace_of_their_generations(connection: Connection) -> None:
    user_id = make_user(connection)
    render_id = make_render(connection, user_id)
    rendition_id = make_rendition(connection, render_id, asset_id=make_ready_asset(connection, user_id))
    job_id = make_job(connection, user_id, render_id=render_id)
    storyboard_id = make_storyboard(connection, job_id)
    scene_audio = make_asset(connection, kind="audio", storage_key=f"tts/{token()}.mp3")
    scene_id = make_scene(connection, storyboard_id, audio_asset_id=scene_audio)
    event_id = make_event(connection, job_id)
    link_id = make_share_link(connection, job_id, rendition_id)
    other_job = make_job(connection, make_user(connection))

    delete_user(connection, user_id)

    for table, key in (
        ("jobs", job_id),
        ("storyboards", storyboard_id),
        ("scenes", scene_id),
        ("job_events", event_id),
        ("share_links", link_id),
    ):
        assert count(connection, table, key) == 0, table
    assert count(connection, "jobs", other_job) == 1


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"version": 0}, "ck_storyboards_version_positive"),
        ({"origin": "model"}, "ck_storyboards_origin"),
        ({"content": []}, "ck_storyboards_content_object"),
    ],
)
def test_storyboard_checks(connection: Connection, overrides: dict[str, Any], constraint: str) -> None:
    job_id = make_job(connection, make_user(connection))

    with rejected(connection, constraint):
        make_storyboard(connection, job_id, **overrides)


@pytest.mark.parametrize("origin", ["planner", "critic", "regeneration", "user"])
def test_storyboards_accept_every_documented_origin(connection: Connection, origin: str) -> None:
    storyboard_id = make_storyboard(connection, make_job(connection, make_user(connection)), origin=origin)

    assert column_value(connection, "storyboards", storyboard_id, "approved_at") is None


def test_a_storyboard_defaults_to_the_planner_origin(connection: Connection) -> None:
    storyboard_id = make_storyboard(connection, make_job(connection, make_user(connection)))

    assert column_value(connection, "storyboards", storyboard_id, "origin") == "planner"


def test_a_job_has_one_storyboard_per_version(connection: Connection) -> None:
    job_id = make_job(connection, make_user(connection))
    make_storyboard(connection, job_id)

    with rejected(connection, "uq_storyboards_job_id_version"):
        make_storyboard(connection, job_id)
    make_storyboard(connection, job_id, version=2)
    make_storyboard(connection, make_job(connection, make_user(connection)))


def test_an_approver_needs_an_approval_time(connection: Connection) -> None:
    user_id = make_user(connection)
    job_id = make_job(connection, user_id)

    with rejected(connection, "ck_storyboards_approval_consistent"):
        make_storyboard(connection, job_id, approved_by=user_id)
    approved = make_storyboard(connection, job_id, approved_by=user_id, approved_at=NOW)
    update(connection, "storyboards", approved, approved_by=None)

    assert column_value(connection, "storyboards", approved, "approved_at") == NOW


def test_deleting_the_approver_keeps_the_storyboard(connection: Connection) -> None:
    owner_id = make_user(connection)
    approver_id = make_user(connection)
    storyboard_id = make_storyboard(
        connection, make_job(connection, owner_id), approved_by=approver_id, approved_at=NOW
    )

    delete_user(connection, approver_id)

    assert column_value(connection, "storyboards", storyboard_id, "approved_by") is None
    assert column_value(connection, "storyboards", storyboard_id, "approved_at") == NOW


def test_deleting_a_job_deletes_its_storyboards_and_scenes(connection: Connection) -> None:
    job_id = make_job(connection, make_user(connection))
    storyboard_id = make_storyboard(connection, job_id)
    scene_id = make_scene(connection, storyboard_id)

    connection.execute(text("DELETE FROM jobs WHERE id = :id"), {"id": job_id})

    assert count(connection, "storyboards", storyboard_id) == 0
    assert count(connection, "scenes", scene_id) == 0


@pytest.fixture
def storyboard_id(connection: Connection) -> UUID:
    return make_storyboard(connection, make_job(connection, make_user(connection)))


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"scene_key": "Intro"}, "ck_scenes_scene_key_format"),
        ({"scene_key": "1intro"}, "ck_scenes_scene_key_format"),
        ({"scene_key": "in_tro"}, "ck_scenes_scene_key_format"),
        ({"scene_key": "a" * 33}, "ck_scenes_scene_key_format"),
        ({"scene_key": ""}, "ck_scenes_scene_key_format"),
        ({"position": -1}, "ck_scenes_position_non_negative"),
        ({"target_duration_ms": 999}, "ck_scenes_target_duration_ms_range"),
        ({"target_duration_ms": 120_001}, "ck_scenes_target_duration_ms_range"),
        ({"actual_duration_ms": -1}, "ck_scenes_actual_duration_ms_non_negative"),
        ({"status": "done"}, "ck_scenes_status"),
        ({"repair_attempts": -1}, "ck_scenes_repair_attempts_range"),
        ({"repair_attempts": 4}, "ck_scenes_repair_attempts_range"),
        ({"word_timestamps": {}}, "ck_scenes_word_timestamps_array"),
        ({"module": []}, "ck_scenes_module_object"),
        ({"attempt_log": {}}, "ck_scenes_attempt_log_array"),
        ({"error_code": "Invalid"}, "ck_scenes_error_code_format"),
        ({"narration": "n" * 2001}, "ck_scenes_narration_length"),
        ({"visual_brief": "v" * 4001}, "ck_scenes_visual_brief_length"),
    ],
)
def test_scene_checks(connection: Connection, storyboard_id: UUID, overrides: dict[str, Any], constraint: str) -> None:
    with rejected(connection, constraint):
        make_scene(connection, storyboard_id, **overrides)


@pytest.mark.parametrize("attempts", [0, 1, 2, 3])
def test_scenes_accept_up_to_three_repair_attempts(connection: Connection, storyboard_id: UUID, attempts: int) -> None:
    scene_id = make_scene(connection, storyboard_id, repair_attempts=attempts)

    assert column_value(connection, "scenes", scene_id, "repair_attempts") == attempts


@pytest.mark.parametrize("status", ["pending", "voiced", "generated", "validated", "failed"])
def test_scenes_accept_every_documented_status(connection: Connection, storyboard_id: UUID, status: str) -> None:
    make_scene(connection, storyboard_id, status=status)


def test_a_new_scene_is_pending_without_a_module_or_attempts(connection: Connection, storyboard_id: UUID) -> None:
    scene_id = make_scene(connection, storyboard_id)

    assert column_value(connection, "scenes", scene_id, "status") == "pending"
    assert column_value(connection, "scenes", scene_id, "module") is None
    assert column_value(connection, "scenes", scene_id, "attempt_log") == []
    assert column_value(connection, "scenes", scene_id, "is_fallback") is False
    assert column_value(connection, "scenes", scene_id, "repair_attempts") == 0


def test_a_scene_records_its_module_attempts_and_fallback(connection: Connection, storyboard_id: UUID) -> None:
    scene_id = make_scene(
        connection,
        storyboard_id,
        status="generated",
        module={"sceneId": "intro", "builder": "ctx.at(0)", "css": "", "assets": []},
        attempt_log=[{"kind": "initial", "issueCodes": ["css_scope"]}, {"kind": "fallback", "issueCodes": []}],
        is_fallback=True,
        repair_attempts=2,
        word_timestamps=[{"word": "Vaccines", "startMs": 0, "endMs": 400}],
    )

    assert column_value(connection, "scenes", scene_id, "is_fallback") is True
    assert column_value(connection, "scenes", scene_id, "attempt_log")[1]["kind"] == "fallback"


def test_scene_keys_and_positions_are_unique_per_storyboard(connection: Connection, storyboard_id: UUID) -> None:
    make_scene(connection, storyboard_id)

    with rejected(connection, "uq_scenes_storyboard_id_scene_key"):
        make_scene(connection, storyboard_id, position=1)
    with rejected(connection, "uq_scenes_storyboard_id_position"):
        make_scene(connection, storyboard_id, scene_key="second")
    make_scene(connection, storyboard_id, scene_key="second", position=1)
    other = make_storyboard(connection, make_job(connection, make_user(connection)))
    make_scene(connection, other)


def test_positions_swap_inside_one_transaction_with_deferred_constraints(
    connection: Connection, storyboard_id: UUID
) -> None:
    first = make_scene(connection, storyboard_id)
    second = make_scene(connection, storyboard_id, scene_key="second", position=1)

    with rejected(connection, "uq_scenes_storyboard_id_position"):
        update(connection, "scenes", first, position=1)
    connection.execute(text("SET CONSTRAINTS uq_scenes_storyboard_id_position DEFERRED"))
    update(connection, "scenes", first, position=1)
    update(connection, "scenes", second, position=0)
    connection.execute(text("SET CONSTRAINTS uq_scenes_storyboard_id_position IMMEDIATE"))

    assert column_value(connection, "scenes", first, "position") == 1
    assert column_value(connection, "scenes", second, "position") == 0


def test_deleting_a_scene_asset_clears_the_link(connection: Connection, storyboard_id: UUID) -> None:
    audio = make_asset(connection, kind="audio", storage_key=f"tts/{token()}.mp3")
    html = make_asset(connection, kind="html", storage_key=f"media/u/test/{token()}.html")
    scene_id = make_scene(connection, storyboard_id, audio_asset_id=audio, html_asset_id=html)

    connection.execute(text("DELETE FROM assets WHERE id IN (:audio, :html)"), {"audio": audio, "html": html})

    assert column_value(connection, "scenes", scene_id, "audio_asset_id") is None
    assert column_value(connection, "scenes", scene_id, "html_asset_id") is None


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"type": "Stage"}, "ck_job_events_type_format"),
        ({"type": "stage."}, "ck_job_events_type_format"),
        ({"type": "stage.started.too-long"}, "ck_job_events_type_format"),
        ({"type": "a" * 65}, "ck_job_events_type_format"),
        ({"payload": []}, "ck_job_events_payload_object"),
    ],
)
def test_job_event_checks(connection: Connection, overrides: dict[str, Any], constraint: str) -> None:
    job_id = make_job(connection, make_user(connection))

    with rejected(connection, constraint):
        make_event(connection, job_id, **overrides)


@pytest.mark.parametrize("event_type", ["stage.started", "scene.voiced", "job.completed", "guard", "render.progress"])
def test_job_events_accept_dotted_lowercase_types(connection: Connection, event_type: str) -> None:
    event_id = make_event(connection, make_job(connection, make_user(connection)), type=event_type, stage=None)

    assert column_value(connection, "job_events", event_id, "payload") == {}


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE job_events SET stage = 'voicing' WHERE id = :id",
        "UPDATE job_events SET payload = '{\"x\": 1}'::jsonb WHERE id = :id",
        "DELETE FROM job_events WHERE id = :id",
    ],
)
def test_job_events_are_append_only(connection: Connection, statement: str) -> None:
    event_id = make_event(connection, make_job(connection, make_user(connection)))

    with rejected(connection, "append-only"):
        connection.execute(text(statement), {"id": event_id})


def test_job_events_allow_the_retention_purge(connection: Connection) -> None:
    event_id = make_event(connection, make_job(connection, make_user(connection)))

    connection.execute(text("SET LOCAL motionile.allow_purge = 'on'"))
    connection.execute(text("DELETE FROM job_events WHERE id = :id"), {"id": event_id})

    assert count(connection, "job_events", event_id) == 0


def test_deleting_a_job_deletes_its_events_despite_the_trigger(connection: Connection) -> None:
    job_id = make_job(connection, make_user(connection))
    event_id = make_event(connection, job_id)

    connection.execute(text("DELETE FROM jobs WHERE id = :id"), {"id": job_id})

    assert count(connection, "job_events", event_id) == 0


def test_the_append_only_trigger_is_attached_to_job_events(connection: Connection) -> None:
    query = text("SELECT tgname FROM pg_trigger WHERE tgrelid = CAST('job_events' AS regclass) AND NOT tgisinternal")

    assert set(connection.execute(query).scalars()) == {"trg_job_events_append_only"}


def test_a_job_event_needs_an_existing_job(connection: Connection) -> None:
    with rejected(connection, "fk_job_events_job_id_jobs"):
        make_event(connection, uuid4())


@pytest.fixture
def rendition_for_job(connection: Connection) -> tuple[UUID, UUID]:
    user_id = make_user(connection)
    render_id = make_render(connection, user_id)
    return make_job(connection, user_id, render_id=render_id), make_rendition(connection, render_id)


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"slug": "short"}, "ck_share_links_slug_format"),
        ({"slug": "s" * 33}, "ck_share_links_slug_format"),
        ({"slug": "has space in it!"}, "ck_share_links_slug_format"),
        ({"view_count": -1}, "ck_share_links_view_count_non_negative"),
    ],
)
def test_share_link_checks(
    connection: Connection, rendition_for_job: tuple[UUID, UUID], overrides: dict[str, Any], constraint: str
) -> None:
    job_id, rendition_id = rendition_for_job

    with rejected(connection, constraint):
        make_share_link(connection, job_id, rendition_id, **overrides)


def test_a_new_share_link_is_private_and_unviewed(connection: Connection, rendition_for_job: tuple[UUID, UUID]) -> None:
    job_id, rendition_id = rendition_for_job

    link_id = make_share_link(connection, job_id, rendition_id, slug="Ab_-0123456789")

    assert column_value(connection, "share_links", link_id, "is_public") is False
    assert column_value(connection, "share_links", link_id, "view_count") == 0
    assert column_value(connection, "share_links", link_id, "revoked_at") is None


def test_share_link_slugs_are_unique(connection: Connection, rendition_for_job: tuple[UUID, UUID]) -> None:
    job_id, rendition_id = rendition_for_job
    make_share_link(connection, job_id, rendition_id, slug="shared-slug-1")

    with rejected(connection, "uq_share_links_slug"):
        make_share_link(connection, job_id, rendition_id, slug="shared-slug-1")


def test_deleting_a_rendition_deletes_its_share_links(
    connection: Connection, rendition_for_job: tuple[UUID, UUID]
) -> None:
    job_id, rendition_id = rendition_for_job
    link_id = make_share_link(connection, job_id, rendition_id)

    connection.execute(text("DELETE FROM renditions WHERE id = :id"), {"id": rendition_id})

    assert count(connection, "share_links", link_id) == 0
    assert count(connection, "jobs", job_id) == 1


def test_deleting_a_job_deletes_its_share_links(connection: Connection, rendition_for_job: tuple[UUID, UUID]) -> None:
    job_id, rendition_id = rendition_for_job
    link_id = make_share_link(connection, job_id, rendition_id)

    connection.execute(text("DELETE FROM jobs WHERE id = :id"), {"id": job_id})

    assert count(connection, "share_links", link_id) == 0
    assert count(connection, "renditions", rendition_id) == 1


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"key": "planner"}, "ck_prompt_templates_key_format"),
        ({"key": "Planner.storyboard"}, "ck_prompt_templates_key_format"),
        ({"key": "planner.story-board"}, "ck_prompt_templates_key_format"),
    ],
)
def test_prompt_template_checks(connection: Connection, overrides: dict[str, Any], constraint: str) -> None:
    with rejected(connection, constraint):
        make_template(connection, **overrides)


def test_prompt_template_keys_are_unique(connection: Connection) -> None:
    make_template(connection, key="planner.storyboard")

    with rejected(connection, "uq_prompt_templates_key"):
        make_template(connection, key="planner.storyboard")


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"version": 0}, "ck_prompt_versions_version_positive"),
        ({"eval_status": "unknown"}, "ck_prompt_versions_eval_status"),
        ({"checksum": b"short"}, "ck_prompt_versions_checksum_length"),
        ({"variables": {}}, "ck_prompt_versions_variables_array"),
        ({"eval_report": []}, "ck_prompt_versions_eval_report_object"),
        ({"canary": "short"}, "ck_prompt_versions_canary_length"),
        ({"canary": "c" * 65}, "ck_prompt_versions_canary_length"),
    ],
)
def test_prompt_version_checks(connection: Connection, overrides: dict[str, Any], constraint: str) -> None:
    template_id = make_template(connection)

    with rejected(connection, constraint):
        make_prompt_version(connection, template_id, **overrides)


def test_a_prompt_version_starts_pending_without_a_report(connection: Connection) -> None:
    version_id = make_prompt_version(connection, make_template(connection))

    assert column_value(connection, "prompt_versions", version_id, "eval_status") == "pending"
    assert column_value(connection, "prompt_versions", version_id, "variables") == []
    assert column_value(connection, "prompt_versions", version_id, "eval_report") is None


def test_versions_are_unique_per_template_by_number_and_by_body(connection: Connection) -> None:
    template_id = make_template(connection)
    shared = digest("shared")
    make_prompt_version(connection, template_id, checksum=shared)

    with rejected(connection, "uq_prompt_versions_template_id_version"):
        make_prompt_version(connection, template_id)
    with rejected(connection, "uq_prompt_versions_template_id_checksum"):
        make_prompt_version(connection, template_id, version=2, checksum=shared)
    make_prompt_version(connection, template_id, version=2)
    make_prompt_version(connection, make_template(connection), checksum=shared)


def test_a_template_and_its_active_version_can_be_written_in_one_transaction(connection: Connection) -> None:
    template_id = uuid4()
    version_id = uuid4()

    insert(connection, "prompt_templates", id=template_id, key="planner.circular", active_version_id=version_id)
    make_prompt_version(connection, template_id, id=version_id)
    connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    assert column_value(connection, "prompt_templates", template_id, "active_version_id") == version_id


def test_an_active_version_must_exist_by_the_end_of_the_transaction(connection: Connection) -> None:
    make_template(connection, active_version_id=uuid4())

    with rejected(connection, "fk_prompt_templates_active_version_id_prompt_versions"):
        connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_the_active_version_of_a_template_cannot_be_deleted(connection: Connection) -> None:
    template_id = make_template(connection)
    version_id = make_prompt_version(connection, template_id)
    update(connection, "prompt_templates", template_id, active_version_id=version_id)

    with rejected(connection, "violates foreign key constraint"):
        connection.execute(text("DELETE FROM prompt_versions WHERE id = :id"), {"id": version_id})


def test_deleting_a_template_deletes_its_versions(connection: Connection) -> None:
    template_id = make_template(connection)
    version_id = make_prompt_version(connection, template_id)
    update(connection, "prompt_templates", template_id, active_version_id=version_id)

    connection.execute(text("DELETE FROM prompt_templates WHERE id = :id"), {"id": template_id})
    connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    assert count(connection, "prompt_versions", version_id) == 0


def test_deleting_the_author_keeps_the_prompt_version(connection: Connection) -> None:
    author_id = make_user(connection)
    version_id = make_prompt_version(connection, make_template(connection), created_by=author_id)

    delete_user(connection, author_id)

    assert column_value(connection, "prompt_versions", version_id, "created_by") is None


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"status": "done", "finished_at": NOW}, "ck_eval_runs_status"),
        ({"trigger": "manual"}, "ck_eval_runs_trigger"),
        ({"suite": "Planner"}, "ck_eval_runs_suite_format"),
        ({"suite": "1planner"}, "ck_eval_runs_suite_format"),
        ({"suite": "s" * 61}, "ck_eval_runs_suite_format"),
        ({"dataset_version": ""}, "ck_eval_runs_dataset_version_format"),
        ({"dataset_version": "has space"}, "ck_eval_runs_dataset_version_format"),
        ({"dataset_version": "v" * 41}, "ck_eval_runs_dataset_version_format"),
        ({"prompt_version_ids": [uuid4() for _ in range(101)]}, "ck_eval_runs_prompt_version_ids_size"),
        ({"model_configuration": []}, "ck_eval_runs_model_configuration_object"),
        ({"scores": []}, "ck_eval_runs_scores_object"),
        ({"error_code": "Bad"}, "ck_eval_runs_error_code_format"),
    ],
)
def test_eval_run_value_checks(connection: Connection, overrides: dict[str, Any], constraint: str) -> None:
    with rejected(connection, constraint):
        make_eval_run(connection, **overrides)


def test_a_new_eval_run_is_running_with_empty_results(connection: Connection) -> None:
    run_id = make_eval_run(connection)

    assert column_value(connection, "eval_runs", run_id, "status") == "running"
    assert column_value(connection, "eval_runs", run_id, "passed") is None
    assert column_value(connection, "eval_runs", run_id, "finished_at") is None
    assert column_value(connection, "eval_runs", run_id, "prompt_version_ids") == []
    assert column_value(connection, "eval_runs", run_id, "model_configuration") == {}
    assert column_value(connection, "eval_runs", run_id, "scores") == {}
    assert column_value(connection, "eval_runs", run_id, "started_at") is not None


@pytest.mark.parametrize("trigger", ["ci", "nightly", "admin"])
def test_eval_runs_accept_every_documented_trigger(connection: Connection, trigger: str) -> None:
    make_eval_run(connection, trigger=trigger)


def test_a_running_run_has_no_finish_time_and_no_verdict(connection: Connection) -> None:
    with rejected(connection, "ck_eval_runs_finished_consistent"):
        make_eval_run(connection, finished_at=NOW)
    with rejected(connection, "ck_eval_runs_passed_consistent"):
        make_eval_run(connection, passed=True)


def test_a_finished_run_has_a_finish_time_and_a_verdict(connection: Connection) -> None:
    with rejected(connection, "ck_eval_runs_finished_consistent"):
        make_eval_run(connection, status="finished", passed=True)
    with rejected(connection, "ck_eval_runs_passed_consistent"):
        make_eval_run(connection, status="finished", finished_at=NOW)
    passing = make_finished_run(connection, scores={"schema_validity": 0.99})
    failing = make_eval_run(connection, status="finished", passed=False, finished_at=NOW)

    assert column_value(connection, "eval_runs", passing, "passed") is True
    assert column_value(connection, "eval_runs", failing, "passed") is False


def test_an_errored_run_names_its_error_and_has_no_verdict(connection: Connection) -> None:
    with rejected(connection, "ck_eval_runs_errored_has_error"):
        make_eval_run(connection, status="errored", finished_at=NOW)
    with rejected(connection, "ck_eval_runs_passed_consistent"):
        make_eval_run(connection, status="errored", finished_at=NOW, error_code="dataset_missing", passed=False)
    with rejected(connection, "ck_eval_runs_errored_has_error"):
        make_eval_run(connection, error_code="dataset_missing")
    make_eval_run(connection, status="errored", finished_at=NOW, error_code="dataset_missing")


def test_a_run_moves_from_running_to_finished_by_one_update(connection: Connection) -> None:
    run_id = make_eval_run(connection)

    update(connection, "eval_runs", run_id, status="finished", passed=True, finished_at=NOW, scores={"f1": 0.9})

    assert column_value(connection, "eval_runs", run_id, "scores") == {"f1": 0.9}


def test_runs_covering_a_prompt_version_are_found_through_the_array_index(connection: Connection) -> None:
    covered = uuid4()
    other = uuid4()
    first = make_finished_run(connection, prompt_version_ids=[covered, other])
    second = make_finished_run(connection, prompt_version_ids=[covered])
    make_finished_run(connection, prompt_version_ids=[other])
    query = text("SELECT id FROM eval_runs WHERE prompt_version_ids @> ARRAY[CAST(:id AS uuid)]")

    found = set(connection.execute(query, {"id": covered}).scalars())

    assert found == {first, second}
    assert "gin" in index_definition(connection, "ix_eval_runs_prompt_version_ids")


def test_deleting_the_starting_admin_keeps_the_run(connection: Connection) -> None:
    admin_id = make_user(connection)
    run_id = make_eval_run(connection, trigger="admin", created_by=admin_id)

    delete_user(connection, admin_id)

    assert count(connection, "eval_runs", run_id) == 1
    assert column_value(connection, "eval_runs", run_id, "created_by") is None


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"status": "deleted"}, "ck_skills_status"),
        ({"slug": "Clean"}, "ck_skills_slug_format"),
        ({"slug": "-clean"}, "ck_skills_slug_format"),
        ({"slug": "clean--style"}, "ck_skills_slug_format"),
        ({"slug": "s" * 65}, "ck_skills_slug_format"),
        ({"name": ""}, "ck_skills_name_length"),
        ({"name": "n" * 65}, "ck_skills_name_length"),
        ({"description": ""}, "ck_skills_description_length"),
        ({"description": "d" * 1025}, "ck_skills_description_length"),
    ],
)
def test_skill_value_checks(connection: Connection, overrides: dict[str, Any], constraint: str) -> None:
    with rejected(connection, constraint):
        make_system_skill(connection, **overrides)


def test_a_skill_is_system_or_private(connection: Connection) -> None:
    with rejected(connection, "ck_skills_visibility"):
        make_private_skill(connection, make_user(connection), visibility="public")


def test_system_skills_have_no_owner_and_private_skills_have_one(connection: Connection) -> None:
    user_id = make_user(connection)

    with rejected(connection, "ck_skills_ownership"):
        make_system_skill(connection, owner_user_id=user_id)
    with rejected(connection, "ck_skills_ownership"):
        make_private_skill(connection, user_id, visibility="system")
    with rejected(connection, "ck_skills_ownership"):
        insert(
            connection,
            "skills",
            slug="orphan",
            name="Orphan",
            description="No owner.",
            visibility="private",
        )
    make_system_skill(connection)
    make_private_skill(connection, user_id)


def test_a_new_skill_is_an_enabled_draft(connection: Connection) -> None:
    skill_id = make_system_skill(connection)

    assert column_value(connection, "skills", skill_id, "status") == "draft"
    assert column_value(connection, "skills", skill_id, "is_enabled") is True
    assert column_value(connection, "skills", skill_id, "current_version_id") is None
    assert column_value(connection, "skills", skill_id, "deleted_at") is None


def test_system_skill_slugs_are_unique_among_live_skills(connection: Connection) -> None:
    make_system_skill(connection, slug="clean")

    with rejected(connection, "ix_skills_owner_user_id_slug"):
        make_system_skill(connection, slug="clean")


def test_private_skill_slugs_are_unique_per_owner(connection: Connection) -> None:
    first_user = make_user(connection)
    make_private_skill(connection, first_user, slug="mine")

    with rejected(connection, "ix_skills_owner_user_id_slug"):
        make_private_skill(connection, first_user, slug="mine")
    make_private_skill(connection, make_user(connection), slug="mine")
    make_system_skill(connection, slug="mine")


def test_a_deleted_skill_does_not_block_its_slug(connection: Connection) -> None:
    skill_id = make_system_skill(connection, slug="retired")
    update(connection, "skills", skill_id, deleted_at=NOW)

    make_system_skill(connection, slug="retired")


def test_deleting_a_user_deletes_their_skills_only(connection: Connection) -> None:
    user_id = make_user(connection)
    private = make_private_skill(connection, user_id)
    system = make_system_skill(connection)

    delete_user(connection, user_id)

    assert count(connection, "skills", private) == 0
    assert count(connection, "skills", system) == 1


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"version": 0}, "ck_skill_versions_version_positive"),
        ({"scan_status": "clean"}, "ck_skill_versions_scan_status"),
        ({"checksum": b"short"}, "ck_skill_versions_checksum_length"),
        ({"frontmatter": []}, "ck_skill_versions_frontmatter_object"),
        ({"body_md": "b" * 100_001}, "ck_skill_versions_body_md_length"),
        ({"scan_status": "passed"}, "ck_skill_versions_scanned_consistent"),
        ({"scanned_at": NOW}, "ck_skill_versions_scanned_consistent"),
    ],
)
def test_skill_version_checks(connection: Connection, overrides: dict[str, Any], constraint: str) -> None:
    skill_id = make_system_skill(connection)

    with rejected(connection, constraint):
        make_skill_version(connection, skill_id, **overrides)


def test_a_scanned_version_records_when_the_verdict_was_reached(connection: Connection) -> None:
    skill_id = make_system_skill(connection)

    pending = make_skill_version(connection, skill_id)
    passed = make_skill_version(connection, skill_id, version=2, scan_status="passed", scanned_at=NOW)
    flagged = make_skill_version(
        connection, skill_id, version=3, scan_status="flagged", scanned_at=NOW, scan_report={"findings": ["x"]}
    )

    assert column_value(connection, "skill_versions", pending, "scan_status") == "pending"
    assert column_value(connection, "skill_versions", passed, "scanned_at") == NOW
    assert column_value(connection, "skill_versions", flagged, "scan_report") == {"findings": ["x"]}


def test_versions_are_unique_per_skill(connection: Connection) -> None:
    skill_id = make_system_skill(connection)
    make_skill_version(connection, skill_id)

    with rejected(connection, "uq_skill_versions_skill_id_version"):
        make_skill_version(connection, skill_id)
    make_skill_version(connection, skill_id, version=2)
    make_skill_version(connection, make_system_skill(connection))


def test_the_current_version_is_deferred_and_cleared_when_the_version_is_deleted(connection: Connection) -> None:
    skill_id = uuid4()
    version_id = uuid4()

    insert(
        connection,
        "skills",
        id=skill_id,
        slug="circular",
        name="Circular",
        description="Written in one transaction.",
        visibility="system",
        current_version_id=version_id,
    )
    make_skill_version(connection, skill_id, id=version_id)
    connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    connection.execute(text("DELETE FROM skill_versions WHERE id = :id"), {"id": version_id})

    assert column_value(connection, "skills", skill_id, "current_version_id") is None
    assert count(connection, "skills", skill_id) == 1


def test_the_current_version_must_exist_by_the_end_of_the_transaction(connection: Connection) -> None:
    make_system_skill(connection, current_version_id=uuid4())

    with rejected(connection, "fk_skills_current_version_id_skill_versions"):
        connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_deleting_a_skill_deletes_its_versions_files_and_embeddings(connection: Connection) -> None:
    skill_id = make_system_skill(connection)
    version_id = make_skill_version(connection, skill_id)
    file_id = make_skill_file(connection, version_id)
    insert(connection, "skill_embeddings", skill_version_id=version_id, embedding=vector_of(1.0), model="test-model")

    connection.execute(text("DELETE FROM skills WHERE id = :id"), {"id": skill_id})

    assert count(connection, "skill_versions", version_id) == 0
    assert count(connection, "skill_files", file_id) == 0
    assert count(connection, "skill_embeddings", version_id) == 0


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"path": "../secrets.txt"}, "ck_skill_files_path_safe"),
        ({"path": "assets/../tokens.json"}, "ck_skill_files_path_safe"),
        ({"path": "/absolute.json"}, "ck_skill_files_path_safe"),
        ({"path": "assets//tokens.json"}, "ck_skill_files_path_safe"),
        ({"path": "assets/to kens.json"}, "ck_skill_files_path_safe"),
        ({"path": "a" * 256}, "ck_skill_files_path_safe"),
        ({"size_bytes": -1}, "ck_skill_files_size_bytes_non_negative"),
        ({"sha256": b"short"}, "ck_skill_files_sha256_length"),
    ],
)
def test_skill_file_checks(connection: Connection, overrides: dict[str, Any], constraint: str) -> None:
    version_id = make_skill_version(connection, make_system_skill(connection))

    with rejected(connection, constraint):
        make_skill_file(connection, version_id, **overrides)


def test_skill_files_are_unique_per_version_by_path(connection: Connection) -> None:
    version_id = make_skill_version(connection, make_system_skill(connection))
    make_skill_file(connection, version_id)

    with rejected(connection, "uq_skill_files_skill_version_id_path"):
        make_skill_file(connection, version_id)
    make_skill_file(connection, version_id, path="assets/other.json")


def test_the_asset_of_a_skill_file_cannot_be_deleted_on_its_own(connection: Connection) -> None:
    version_id = make_skill_version(connection, make_system_skill(connection))
    asset_id = make_asset(connection, kind="skill_file", storage_key=f"skills/{token()}.json")
    make_skill_file(connection, version_id, asset_id=asset_id)

    with rejected(connection, "violates foreign key constraint"):
        connection.execute(text("DELETE FROM assets WHERE id = :id"), {"id": asset_id})


def test_the_embedding_column_has_the_configured_dimension(connection: Connection) -> None:
    query = text(
        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
        "WHERE attrelid = CAST('skill_embeddings' AS regclass) AND attname = 'embedding'"
    )

    assert connection.execute(query).scalar_one() == f"vector({EMBEDDING_DIMENSIONS})"


def test_embeddings_reject_the_wrong_dimension(connection: Connection) -> None:
    version_id = make_skill_version(connection, make_system_skill(connection))

    with rejected(connection, "dimensions"):
        insert(connection, "skill_embeddings", skill_version_id=version_id, embedding=[1.0, 2.0], model="test-model")


def test_embeddings_are_searched_by_cosine_distance_through_the_hnsw_index(connection: Connection) -> None:
    near = make_skill_version(connection, make_system_skill(connection))
    far = make_skill_version(connection, make_system_skill(connection))
    insert(connection, "skill_embeddings", skill_version_id=near, embedding=vector_of(1.0), model="test-model")
    opposite = [0.0, 1.0, *([0.0] * (EMBEDDING_DIMENSIONS - 2))]
    insert(connection, "skill_embeddings", skill_version_id=far, embedding=opposite, model="test-model")
    table = metadata.tables["skill_embeddings"]

    nearest = connection.execute(
        sa.select(table.c.skill_version_id).order_by(table.c.embedding.cosine_distance(vector_of(1.0))).limit(1)
    ).scalar_one()

    assert nearest == near
    definition = index_definition(connection, "ix_skill_embeddings_embedding")
    assert "hnsw" in definition
    assert "vector_cosine_ops" in definition
    assert "m='16'" in definition
    assert "ef_construction='64'" in definition


def test_a_skill_version_has_one_embedding(connection: Connection) -> None:
    version_id = make_skill_version(connection, make_system_skill(connection))
    insert(connection, "skill_embeddings", skill_version_id=version_id, embedding=vector_of(1.0), model="test-model")

    with rejected(connection, "pk_skill_embeddings"):
        insert(connection, "skill_embeddings", skill_version_id=version_id, embedding=vector_of(2.0), model="other")


def test_deleting_a_job_clears_the_usage_records_link_without_touching_the_record(connection: Connection) -> None:
    user_id = make_user(connection)
    job_id = make_job(connection, user_id)
    record_id = make_usage_record(connection, user_id, job_id)

    connection.execute(text("DELETE FROM jobs WHERE id = :id"), {"id": job_id})

    assert count(connection, "usage_records", record_id) == 1
    assert column_value(connection, "usage_records", record_id, "job_id") is None


def test_usage_records_stay_append_only(connection: Connection) -> None:
    user_id = make_user(connection)
    record_id = make_usage_record(connection, user_id, make_job(connection, user_id))

    with rejected(connection, "append-only"):
        connection.execute(text("UPDATE usage_records SET stage = 'scene' WHERE id = :id"), {"id": record_id})


def test_a_usage_record_must_reference_an_existing_job(connection: Connection) -> None:
    with rejected(connection, "fk_usage_records_job_id_jobs"):
        make_usage_record(connection, make_user(connection), uuid4())


def test_usage_records_without_a_job_remain_valid(connection: Connection) -> None:
    make_usage_record(connection, make_user(connection), None)


def test_permission_catalog_matches_the_database(connection: Connection) -> None:
    keys = set(connection.execute(text("SELECT key FROM permissions")).scalars())

    assert keys == PERMISSION_KEYS
    assert keys >= GENERATION_PERMISSION_KEYS


def granted_to(connection: Connection, role: str) -> set[str]:
    query = text(
        "SELECT permissions.key FROM role_permissions "
        "JOIN roles ON roles.id = role_permissions.role_id "
        "JOIN permissions ON permissions.id = role_permissions.permission_id "
        "WHERE roles.key = :role "
        "AND permissions.key IN ('prompts.manage', 'skills.manage', 'jobs.read_all', 'evals.run')"
    )
    return set(connection.execute(query, {"role": role}).scalars())


def test_admin_reads_all_jobs_and_curates_skills_but_cannot_change_prompts_or_run_evals(
    connection: Connection,
) -> None:
    assert granted_to(connection, "admin") == ADMIN_GENERATION_KEYS


def test_ordinary_users_hold_no_generation_permission(connection: Connection) -> None:
    assert granted_to(connection, "user") == set()
