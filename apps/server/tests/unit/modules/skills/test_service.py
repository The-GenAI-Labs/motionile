from collections.abc import Sequence
from dataclasses import replace

import pytest
from tests.fakes.skills_store import disabled
from tests.unit.engine.ai.support import call_context
from tests.unit.modules.skills.support import ADMIN, CONTEXT, LIBRARY_SIZE, CountingEmbedder, Harness, make_harness

from motionile.core.pagination import Cursor
from motionile.engine.ai.llm.models import LlmUnavailableError
from motionile.engine.ai.ports import SkillLayer
from motionile.engine.ai.skills.loader import SkillDocument, SkillLibraryError
from motionile.modules.skills.catalog import DatabaseSkillCatalog
from motionile.modules.skills.domain import EmbeddingStatus
from motionile.modules.skills.exceptions import (
    SkillEmbeddingUnavailableError,
    SkillLibraryInvalidError,
    SkillNotFoundError,
)


@pytest.fixture
async def seeded(monkeypatch: pytest.MonkeyPatch) -> Harness:
    harness = make_harness(monkeypatch)
    await harness.seeder.sync(harness.documents)
    harness.audit.clear()
    return harness


async def test_the_list_shows_metadata_checksum_prefix_token_count_and_embedding_status(seeded: Harness) -> None:
    listing = await seeded.service.list_skills(None, None, 100)

    assert len(listing.items) == LIBRARY_SIZE
    assert listing.next_cursor is None
    by_slug = {item.slug: item for item in listing.items}
    for document in seeded.documents:
        item = by_slug[document.slug]
        assert item.name == document.name
        assert item.description == document.description
        assert item.layer is document.layer
        assert item.version == 1
        assert item.checksum == document.checksum.hex()[:12]
        assert item.token_count == document.token_count
        assert item.embedding_status is EmbeddingStatus.READY


async def test_the_embedding_status_is_stale_for_another_model_and_missing_without_a_row(seeded: Harness) -> None:
    first, second = seeded.documents[0], seeded.documents[1]
    skill = seeded.world.by_slug(first.slug)
    other = seeded.world.by_slug(second.slug)
    assert skill is not None
    assert other is not None
    skill_version = seeded.world.current_version(skill)
    other_version = seeded.world.current_version(other)
    assert skill_version is not None
    assert other_version is not None
    seeded.world.embeddings[skill_version.id] = (seeded.world.embeddings[skill_version.id][0], "older-model")
    del seeded.world.embeddings[other_version.id]

    listing = await seeded.service.list_skills(None, None, 100)

    statuses = {item.slug: item.embedding_status for item in listing.items}
    assert statuses[first.slug] is EmbeddingStatus.STALE
    assert statuses[second.slug] is EmbeddingStatus.MISSING
    assert list(statuses.values()).count(EmbeddingStatus.READY) == LIBRARY_SIZE - 2


async def test_the_list_filters_by_layer(seeded: Harness) -> None:
    listing = await seeded.service.list_skills(SkillLayer.STYLE, None, 100)

    assert {item.layer for item in listing.items} == {SkillLayer.STYLE}
    assert len(listing.items) == 5


async def test_the_list_pages_with_a_cursor(seeded: Harness) -> None:
    seen: list[str] = []
    cursor: Cursor | None = None
    pages = 0
    while True:
        listing = await seeded.service.list_skills(None, cursor, 7)
        seen.extend(item.slug for item in listing.items)
        pages += 1
        cursor = listing.next_cursor
        if cursor is None:
            break

    assert pages == 5
    assert len(seen) == len(set(seen)) == LIBRARY_SIZE


async def test_the_detail_lists_every_version_newest_first_with_checksum_prefixes(seeded: Harness) -> None:
    original = seeded.documents[2]
    changed = replace(original, checksum=bytes([205]) * 32)
    seeded.documents[2] = changed
    await seeded.seeder.sync(seeded.documents)

    detail = await seeded.service.get_skill(changed.slug)

    assert detail.version == 2
    assert detail.checksum == "cd" * 6
    assert [(version.number, version.checksum) for version in detail.versions] == [
        (2, "cd" * 6),
        (1, original.checksum.hex()[:12]),
    ]


async def test_an_unknown_skill_is_not_found(seeded: Harness) -> None:
    with pytest.raises(SkillNotFoundError):
        await seeded.service.get_skill("does-not-exist")


async def test_reseed_runs_the_sync_and_records_an_admin_audit_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = make_harness(monkeypatch)

    first = await harness.service.reseed(ADMIN, CONTEXT)
    second = await harness.service.reseed(ADMIN, CONTEXT)

    assert (first.created, first.updated, first.unchanged, first.embedded) == (LIBRARY_SIZE, 0, 0, LIBRARY_SIZE)
    assert (second.created, second.updated, second.unchanged, second.embedded) == (0, 0, LIBRARY_SIZE, 0)
    reseeds = [event for event in harness.audit if event.action == "skills.reseeded"]
    assert len(reseeds) == 2
    assert {event.actor_user_id for event in reseeds} == {ADMIN}
    assert {event.actor_type.value for event in reseeds} == {"admin"}
    assert reseeds[1].metadata == {"created": 0, "updated": 0, "unchanged": LIBRARY_SIZE, "embedded": 0}


async def test_reseed_maps_an_unavailable_embedder_to_a_gateway_error(monkeypatch: pytest.MonkeyPatch) -> None:
    embedder = CountingEmbedder()
    embedder.failure = LlmUnavailableError()
    harness = make_harness(monkeypatch, embedder)

    with pytest.raises(SkillEmbeddingUnavailableError):
        await harness.service.reseed(ADMIN, CONTEXT)

    assert harness.audit == []


async def test_reseed_reports_an_invalid_library_without_touching_the_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken() -> Sequence[SkillDocument]:
        raise SkillLibraryError(("domain/physics: the shipped skill is missing",))

    harness = make_harness(monkeypatch, loader=broken)

    with pytest.raises(SkillLibraryInvalidError):
        await harness.service.reseed(ADMIN, CONTEXT)

    assert harness.world.transactions == 0


async def test_the_catalog_serves_summaries_with_token_cost_and_similarity(seeded: Harness) -> None:
    catalog = DatabaseSkillCatalog(seeded.world.transaction, seeded.world.store)
    (query,) = await seeded.embedder.embed([seeded.documents[0].description], call_context())

    nearest = await catalog.nearest(SkillLayer.STYLE, query, 3)

    assert len(nearest) == 3
    scores = [item.similarity or 0.0 for item in nearest]
    assert scores == sorted(scores, reverse=True)
    assert all(item.layer is SkillLayer.STYLE and item.token_count > 0 for item in nearest)
    assert nearest[0].slug == seeded.documents[0].slug
    assert nearest[0].similarity == pytest.approx(1.0)


async def test_the_catalog_loads_bodies_and_style_tokens_in_the_requested_order(seeded: Harness) -> None:
    catalog = DatabaseSkillCatalog(seeded.world.transaction, seeded.world.store)

    loaded = await catalog.load(["whiteboard", "flow-diagram", "whiteboard", "missing-skill", "minimal-dark"])

    assert [skill.summary.slug for skill in loaded] == ["whiteboard", "flow-diagram", "minimal-dark"]
    whiteboard, flow, minimal = loaded
    assert whiteboard.tokens["--mo-bg"] == "#f7f5ee"
    assert dict(flow.tokens) == {}
    assert dict(minimal.tokens) == {}
    assert flow.body.startswith("# Flow diagram")
    assert flow.token_count == flow.summary.token_count == len(flow.body) // 4


async def test_the_catalog_hides_disabled_skills_and_reports_style_existence(seeded: Harness) -> None:
    catalog = DatabaseSkillCatalog(seeded.world.transaction, seeded.world.store)
    disabled(seeded.world, "terminal")

    assert await catalog.style_exists("whiteboard")
    assert not await catalog.style_exists("terminal")
    assert not await catalog.style_exists("flow-diagram")
    assert not await catalog.style_exists("missing-skill")
    assert [item.slug for item in await catalog.by_slugs(["terminal", "blueprint", "blueprint"])] == ["blueprint"]
    assert await catalog.load(["terminal"]) == []
    assert await catalog.by_slugs([]) == []


async def test_the_catalog_lists_the_five_styles_with_palettes_and_no_text(seeded: Harness) -> None:
    catalog = DatabaseSkillCatalog(seeded.world.transaction, seeded.world.store)

    styles = await catalog.styles()

    assert [style.slug for style in styles] == [
        "blueprint",
        "editorial-light",
        "minimal-dark",
        "terminal",
        "whiteboard",
    ]
    assert all({"--mo-bg", "--mo-surface", "--mo-text", "--mo-accent"} <= set(style.palette) for style in styles)
    assert all(not hasattr(style, "body") for style in styles)
    minimal = next(style for style in styles if style.slug == "minimal-dark")
    assert minimal.palette["--mo-bg"] == "#0e0e10"
