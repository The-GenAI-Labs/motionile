from dataclasses import replace

import pytest
from tests.unit.modules.skills.support import LIBRARY_SIZE, CountingEmbedder, Harness, make_harness

from motionile.engine.ai.llm.models import LlmUnavailableError
from motionile.modules.skills.exceptions import SkillEmbeddingDimensionsError
from motionile.modules.skills.seed import SeedReport


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    return make_harness(monkeypatch)


async def test_the_first_sync_creates_every_skill_with_version_one_and_an_embedding(harness: Harness) -> None:
    report = await harness.seeder.sync(harness.documents)

    world = harness.world
    assert report == SeedReport(created=LIBRARY_SIZE, updated=0, unchanged=0, embedded=LIBRARY_SIZE)
    assert len(world.skills) == len(world.versions) == len(world.embeddings) == LIBRARY_SIZE
    for document in harness.documents:
        skill = world.by_slug(document.slug)
        assert skill is not None
        version = world.current_version(skill)
        assert version is not None
        assert (version.number, version.checksum, version.body) == (1, document.checksum, document.body)
        assert version.frontmatter == dict(document.frontmatter)
        assert (skill.name, skill.description) == (document.name, document.description)
        assert world.embeddings[version.id][1] == "fake-embedding"
    assert harness.embedder.texts == [document.description for document in harness.documents]


async def test_a_second_sync_changes_and_embeds_nothing(harness: Harness) -> None:
    await harness.seeder.sync(harness.documents)
    embedded_before = len(harness.embedder.texts)
    versions_before = dict(harness.world.versions)

    report = await harness.seeder.sync(harness.documents)

    assert report == SeedReport(created=0, updated=0, unchanged=LIBRARY_SIZE, embedded=0)
    assert len(harness.embedder.texts) == embedded_before
    assert harness.world.versions == versions_before


async def test_a_changed_checksum_adds_a_version_and_keeps_the_previous_one(harness: Harness) -> None:
    await harness.seeder.sync(harness.documents)
    target = harness.documents[3]
    changed = replace(
        target,
        checksum=b"\x07" * 32,
        description="A brand new description for this skill.",
        body="# Changed\n\nNew text.\n",
    )
    harness.documents[3] = changed
    harness.embedder.texts.clear()

    report = await harness.seeder.sync(harness.documents)

    world = harness.world
    skill = world.by_slug(target.slug)
    assert skill is not None
    assert report == SeedReport(created=0, updated=1, unchanged=LIBRARY_SIZE - 1, embedded=1)
    assert world.version_numbers(target.slug) == [1, 2]
    current = world.current_version(skill)
    assert current is not None
    assert (current.number, current.checksum, current.body) == (2, changed.checksum, changed.body)
    assert skill.description == "A brand new description for this skill."
    assert world.embeddings[current.id][1] == "fake-embedding"
    assert harness.embedder.texts == ["A brand new description for this skill."]
    previous = next(v for v in world.versions.values() if v.skill_id == skill.id and v.number == 1)
    assert previous.checksum == target.checksum
    assert len(world.embeddings) == LIBRARY_SIZE + 1


async def test_a_reverted_file_becomes_a_new_version_rather_than_reusing_an_old_one(harness: Harness) -> None:
    await harness.seeder.sync(harness.documents)
    original = harness.documents[0]
    harness.documents[0] = replace(original, checksum=b"\x01" * 32)
    await harness.seeder.sync(harness.documents)
    harness.documents[0] = original

    report = await harness.seeder.sync(harness.documents)

    assert report.updated == 1
    assert harness.world.version_numbers(original.slug) == [1, 2, 3]


async def test_rows_embedded_with_another_model_are_embedded_again(harness: Harness) -> None:
    await harness.seeder.sync(harness.documents)
    other = CountingEmbedder(model="text-embedding-3-small")

    report = await harness.seeder_for(other).sync(harness.documents)

    assert report == SeedReport(created=0, updated=0, unchanged=LIBRARY_SIZE, embedded=LIBRARY_SIZE)
    assert {model for _, model in harness.world.embeddings.values()} == {"text-embedding-3-small"}
    assert len(harness.world.versions) == LIBRARY_SIZE
    assert len(other.texts) == LIBRARY_SIZE


async def test_a_missing_embedding_is_written_for_an_unchanged_skill(harness: Harness) -> None:
    await harness.seeder.sync(harness.documents)
    skill = harness.world.by_slug(harness.documents[5].slug)
    assert skill is not None
    version = harness.world.current_version(skill)
    assert version is not None
    del harness.world.embeddings[version.id]

    report = await harness.seeder.sync(harness.documents)

    assert report == SeedReport(created=0, updated=0, unchanged=LIBRARY_SIZE, embedded=1)
    assert version.id in harness.world.embeddings


async def test_every_skill_is_written_in_its_own_transaction_after_one_read(harness: Harness) -> None:
    await harness.seeder.sync(harness.documents)

    assert harness.world.transactions == 1 + LIBRARY_SIZE
    assert harness.world.locks == [document.slug for document in harness.documents]


async def test_an_embedding_failure_writes_nothing(harness: Harness) -> None:
    harness.embedder.failure = LlmUnavailableError()

    with pytest.raises(LlmUnavailableError):
        await harness.seeder.sync(harness.documents)

    assert harness.world.skills == {}
    assert harness.world.versions == {}
    assert harness.world.embeddings == {}


async def test_an_embedder_of_the_wrong_size_is_refused_before_any_work(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = make_harness(monkeypatch, CountingEmbedder(dimensions=64))

    with pytest.raises(SkillEmbeddingDimensionsError):
        await harness.seeder.sync(harness.documents)

    assert harness.world.transactions == 0


async def test_creations_and_new_versions_are_audited_by_the_system_with_the_checksum_prefix(harness: Harness) -> None:
    await harness.seeder.sync(harness.documents)
    harness.documents[0] = replace(harness.documents[0], checksum=b"\xab" * 32)
    await harness.seeder.sync(harness.documents)

    created = [event for event in harness.audit if event.action == "skills.created"]
    added = [event for event in harness.audit if event.action == "skills.version_added"]
    assert len(created) == LIBRARY_SIZE
    assert len(added) == 1
    assert {event.actor_type.value for event in harness.audit} == {"system"}
    assert added[0].metadata == {"slug": harness.documents[0].slug, "version": 2, "checksum": "ab" * 6}
    assert created[0].target_type == "skill"
    assert all("body" not in event.metadata for event in harness.audit)


async def test_an_empty_library_is_a_no_op(harness: Harness) -> None:
    report = await harness.seeder.sync([])

    assert report == SeedReport(0, 0, 0, 0)
    assert harness.embedder.texts == []
