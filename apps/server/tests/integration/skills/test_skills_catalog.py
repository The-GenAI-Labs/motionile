import asyncio
from dataclasses import replace
from uuid import uuid4

from sqlalchemy import text
from tests.integration.skills.support import SkillsApi
from tests.unit.engine.ai.skills.support import job, selection
from tests.unit.engine.ai.support import ScriptedClient, StaticPrompts, call_context

from motionile.core.clock import SystemClock
from motionile.core.db import Database
from motionile.engine.ai.llm.embeddings import FakeEmbedder
from motionile.engine.ai.ports import SkillLayer
from motionile.engine.ai.skills.loader import load_library
from motionile.engine.ai.skills.router import LibrarySkillRouter
from motionile.modules.skills import DatabaseSkillCatalog, SkillSeeder
from motionile.modules.skills.repository import SqlSkillRepository

LIBRARY = load_library()
LIBRARY_SIZE = len(LIBRARY)
FAKE_MODEL = "fake-embedding"


def seeder_for(database: Database, embedder: FakeEmbedder | None = None) -> SkillSeeder:
    return SkillSeeder(database.transaction, embedder or FakeEmbedder(), SystemClock(), SqlSkillRepository)


async def description_vector(slug: str) -> list[float]:
    document = next(document for document in LIBRARY if document.slug == slug)
    (vector,) = await FakeEmbedder().embed([document.description], call_context())
    return vector


async def test_the_first_sync_creates_active_ownerless_system_skills_with_scanned_versions(
    skills_api: SkillsApi,
) -> None:
    report = await seeder_for(skills_api.database).sync(LIBRARY)

    rows = await skills_api.rows(
        "SELECT s.slug, s.owner_user_id, s.visibility, s.status, s.is_enabled, s.current_version_id = v.id, "
        "v.version, v.scan_status, v.scanned_at IS NOT NULL, octet_length(v.checksum), e.model, "
        "v.frontmatter -> 'metadata' ->> 'layer', s.name "
        "FROM skills s JOIN skill_versions v ON v.skill_id = s.id "
        "JOIN skill_embeddings e ON e.skill_version_id = v.id ORDER BY s.slug"
    )

    assert (report.created, report.updated, report.unchanged, report.embedded) == (LIBRARY_SIZE, 0, 0, LIBRARY_SIZE)
    assert len(rows) == LIBRARY_SIZE
    by_slug = {row[0]: row for row in rows}
    for document in LIBRARY:
        row = by_slug[document.slug]
        assert row[1:11] == (None, "system", "active", True, True, 1, "passed", True, 32, FAKE_MODEL)
        assert row[11] == document.layer.value
        assert row[12] == document.name


async def test_syncing_again_changes_nothing(skills_api: SkillsApi) -> None:
    seeder = seeder_for(skills_api.database)
    await seeder.sync(LIBRARY)
    before = await skills_api.rows("SELECT id, updated_at FROM skill_versions ORDER BY id")

    report = await seeder.sync(LIBRARY)

    assert (report.created, report.updated, report.unchanged, report.embedded) == (0, 0, LIBRARY_SIZE, 0)
    assert await skills_api.rows("SELECT id, updated_at FROM skill_versions ORDER BY id") == before


async def test_a_changed_file_adds_a_version_moves_the_pointer_and_keeps_the_old_version(
    skills_api: SkillsApi,
) -> None:
    await seeder_for(skills_api.database).sync(LIBRARY)
    index = next(position for position, document in enumerate(LIBRARY) if document.slug == "backend")
    changed = list(LIBRARY)
    changed[index] = replace(
        LIBRARY[index], checksum=b"\x42" * 32, description="Server side development.", body="# Backend\n\nNew.\n"
    )

    report = await seeder_for(skills_api.database).sync(changed)

    assert (report.created, report.updated, report.unchanged, report.embedded) == (0, 1, LIBRARY_SIZE - 1, 1)
    versions = await skills_api.rows(
        "SELECT v.version, v.body_md, s.current_version_id = v.id FROM skill_versions v "
        "JOIN skills s ON s.id = v.skill_id WHERE s.slug = 'backend' ORDER BY v.version"
    )
    assert [(row[0], row[2]) for row in versions] == [(1, False), (2, True)]
    assert versions[0][1] == LIBRARY[index].body
    assert versions[1][1] == "# Backend\n\nNew.\n"
    assert (
        await skills_api.scalar("SELECT description FROM skills WHERE slug = 'backend'") == "Server side development."
    )
    assert await skills_api.scalar("SELECT count(*) FROM skill_embeddings") == LIBRARY_SIZE + 1


async def test_rows_embedded_with_another_model_are_embedded_again_without_new_versions(
    skills_api: SkillsApi,
) -> None:
    await seeder_for(skills_api.database).sync(LIBRARY)

    report = await seeder_for(skills_api.database, FakeEmbedder(model="other-model")).sync(LIBRARY)

    assert (report.created, report.updated, report.unchanged, report.embedded) == (0, 0, LIBRARY_SIZE, LIBRARY_SIZE)
    assert await skills_api.rows("SELECT DISTINCT model FROM skill_embeddings") == [("other-model",)]
    assert await skills_api.scalar("SELECT count(*) FROM skill_versions") == LIBRARY_SIZE


async def test_two_syncs_at_once_create_each_skill_exactly_once(skills_api: SkillsApi) -> None:
    reports = await asyncio.gather(
        seeder_for(skills_api.database).sync(LIBRARY), seeder_for(skills_api.database).sync(LIBRARY)
    )

    assert sum(report.created for report in reports) == LIBRARY_SIZE
    assert sum(report.unchanged for report in reports) == LIBRARY_SIZE
    assert await skills_api.scalar("SELECT count(*) FROM skills WHERE visibility = 'system'") == LIBRARY_SIZE
    assert await skills_api.scalar("SELECT count(*) FROM skill_versions") == LIBRARY_SIZE


async def test_nearest_orders_by_cosine_similarity_within_the_layer(skills_api: SkillsApi) -> None:
    await seeder_for(skills_api.database).sync(LIBRARY)
    catalog = DatabaseSkillCatalog(skills_api.database.transaction)

    nearest = await catalog.nearest(SkillLayer.VISUAL, await description_vector("flow-diagram"), 4)

    assert len(nearest) == 4
    assert nearest[0].slug == "flow-diagram"
    assert nearest[0].similarity is not None
    assert abs(nearest[0].similarity - 1.0) < 1e-6
    scores = [summary.similarity or 0.0 for summary in nearest]
    assert scores == sorted(scores, reverse=True)
    assert {summary.layer for summary in nearest} == {SkillLayer.VISUAL}
    flow = next(document for document in LIBRARY if document.slug == "flow-diagram")
    assert (nearest[0].name, nearest[0].description, nearest[0].token_count) == (
        flow.name,
        flow.description,
        flow.token_count,
    )
    domain = await catalog.nearest(SkillLayer.DOMAIN, await description_vector("backend"), 100)
    assert next(summary.slug for summary in domain) == "backend"
    assert len(domain) == 15


async def test_nearest_skips_disabled_archived_and_deleted_skills(skills_api: SkillsApi) -> None:
    await seeder_for(skills_api.database).sync(LIBRARY)
    catalog = DatabaseSkillCatalog(skills_api.database.transaction)
    await skills_api.execute("UPDATE skills SET is_enabled = false WHERE slug = 'flow-diagram'")
    await skills_api.execute("UPDATE skills SET status = 'archived' WHERE slug = 'timeline-sequence'")
    await skills_api.execute("UPDATE skills SET deleted_at = now() WHERE slug = 'concept-metaphor'")

    nearest = await catalog.nearest(SkillLayer.VISUAL, await description_vector("flow-diagram"), 100)

    slugs = {summary.slug for summary in nearest}
    assert len(slugs) == 7
    assert not slugs & {"flow-diagram", "timeline-sequence", "concept-metaphor"}
    assert [summary.slug for summary in await catalog.by_slugs(["flow-diagram", "backend"])] == ["backend"]
    assert await catalog.load(["flow-diagram"]) == []


async def test_by_slugs_loads_bodies_and_style_tokens_and_reports_styles(skills_api: SkillsApi) -> None:
    await seeder_for(skills_api.database).sync(LIBRARY)
    catalog = DatabaseSkillCatalog(skills_api.database.transaction)

    summaries = await catalog.by_slugs(["terminal", "flow-diagram", "unknown", "terminal"])
    loaded = await catalog.load(["whiteboard", "flow-diagram", "whiteboard", "unknown", "minimal-dark"])

    assert [summary.slug for summary in summaries] == ["flow-diagram", "terminal"]
    assert all(summary.similarity is None for summary in summaries)
    assert [skill.summary.slug for skill in loaded] == ["whiteboard", "flow-diagram", "minimal-dark"]
    documents = {document.slug: document for document in LIBRARY}
    for skill in loaded:
        document = documents[skill.summary.slug]
        assert skill.body == document.body
        assert skill.token_count == document.token_count
    assert loaded[0].tokens["--mo-bg"] == "#f7f5ee"
    assert dict(loaded[1].tokens) == {}
    assert dict(loaded[2].tokens) == {}
    assert await catalog.style_exists("terminal")
    assert not await catalog.style_exists("flow-diagram")
    assert not await catalog.style_exists("unknown")


async def test_only_system_skills_are_served(skills_api: SkillsApi) -> None:
    await seeder_for(skills_api.database).sync(LIBRARY)
    catalog = DatabaseSkillCatalog(skills_api.database.transaction)
    await skills_api.execute(
        "INSERT INTO skills (id, owner_user_id, slug, name, description, visibility, status) "
        "VALUES (:id, :owner, 'my-private-skill', 'Private', 'Mine.', 'private', 'active')",
        id=uuid4(),
        owner=skills_api.media.primary_id,
    )

    assert await catalog.by_slugs(["my-private-skill"]) == []
    assert await catalog.load(["my-private-skill"]) == []
    listing = (await skills_api.curator.get("/v1/admin/skills?limit=100")).json()["items"]
    assert "my-private-skill" not in {item["slug"] for item in listing}
    await skills_api.execute("DELETE FROM skills WHERE slug = 'my-private-skill'")


async def test_the_router_selects_from_the_database_catalog(skills_api: SkillsApi) -> None:
    embedder = FakeEmbedder()
    await seeder_for(skills_api.database).sync(LIBRARY)
    catalog = DatabaseSkillCatalog(skills_api.database.transaction)
    client = ScriptedClient(selection("whiteboard", ["flow-diagram"], ["backend"]))
    router = LibrarySkillRouter(catalog, embedder, client, StaticPrompts())
    snapshot = job("Explain the request lifecycle of a web server step by step", style="whiteboard", hints=["backend"])

    selected = await router.select(snapshot, call_context(), token_budget=12_000)

    assert selected.style.summary.slug == "whiteboard"
    assert selected.style.tokens["--mo-accent"] == "#1d4ed8"
    assert [skill.summary.slug for skill in selected.domain] == ["backend"]
    assert sum(skill.token_count for skill in selected.all) <= 12_000
    context_block = str(client.calls[0].user_blocks[0])
    assert "- backend |" in context_block
    assert "topic hint" in context_block


async def test_the_audit_trail_of_a_seed_never_holds_skill_text(skills_api: SkillsApi) -> None:
    await seeder_for(skills_api.database).sync(LIBRARY)

    rows = await skills_api.rows("SELECT metadata FROM audit_log WHERE action = 'skills.created'")

    assert len(rows) == LIBRARY_SIZE
    assert all(set(row[0]) == {"slug", "version", "checksum"} for row in rows)
    async with skills_api.database.transaction() as session:
        leaked = await session.scalar(text("SELECT count(*) FROM audit_log WHERE metadata::text LIKE '%When to use%'"))
    assert leaked == 0
