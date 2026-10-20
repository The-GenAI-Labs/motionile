import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import text
from tests.integration.credit_support import create_users, purge_credit_data
from tests.integration.media_support import VIDEO_BYTES, MediaApi, purge_media_data

from motionile.core.db import Database
from motionile.core.resources import Resources
from motionile.core.storage.s3 import S3Storage
from motionile.engine.audio.models import VoiceRef
from motionile.modules.media import (
    AssetInUseError,
    AssetKeyExistsError,
    AssetKind,
    AssetNotFoundError,
    AssetSpec,
    AssetStatus,
    assets_for,
    speech_for,
)
from motionile.modules.media.exceptions import AssetKeyTakenError, AssetReferencedError
from motionile.modules.media.repository import NewAssetRow, SqlAssetRepository
from motionile.modules.media.tasks import prune_unused_tts_cache
from motionile.modules.users.tasks import purge_expired_users

VOICE = VoiceRef("fake", "fake-voice-aria", "en")
TEXT = "Every video begins with a question."


@dataclass
class Env:
    resources: Resources
    storage: S3Storage
    users: list[UUID]

    @property
    def database(self) -> Database:
        return self.resources.database

    async def count(self, statement: str) -> int:
        async with self.database.transaction() as session:
            return (await session.execute(text(statement))).scalar_one()


@pytest.fixture
async def env(resources: Resources) -> AsyncIterator[Env]:
    resources.rate_limiter.enabled = False
    storage = resources.storage
    assert isinstance(storage, S3Storage)
    await storage.ensure_bucket()
    users = await create_users(resources.database, 2)
    yield Env(resources, storage, users)
    await purge_media_data(resources.database, users)
    await purge_credit_data(resources.database, [])


async def one_chunk(data: bytes) -> AsyncIterator[bytes]:
    yield data


async def test_concurrent_identical_syntheses_produce_one_entry(env: Env) -> None:
    speech = speech_for(env.resources)
    options = speech.default_options("fake", "en")

    results = await asyncio.gather(
        *[speech.synthesize_text(VOICE, TEXT, options, user_id=env.users[0]) for _ in range(4)]
    )

    assert await env.count("SELECT count(*) FROM tts_cache") == 1
    assert await env.count("SELECT count(*) FROM assets WHERE storage_key LIKE 'tts/%'") == 1
    assert len({result.audio for result in results}) == 1
    assert len({result.words for result in results}) == 1
    paid = sum(1 for result in results if not result.cache_hit)
    assert paid >= 1
    assert await env.count("SELECT count(*) FROM usage_records WHERE stage = 'tts'") == paid
    [key] = await asset_keys(env, "tts/%")
    assert await env.storage.exists(key)


async def asset_keys(env: Env, pattern: str) -> list[str]:
    async with env.database.transaction() as session:
        rows = await session.execute(
            text("SELECT storage_key FROM assets WHERE storage_key LIKE :pattern ORDER BY storage_key"),
            {"pattern": pattern},
        )
        return [row[0] for row in rows]


async def test_a_hit_updates_the_counters_and_costs_nothing(env: Env) -> None:
    speech = speech_for(env.resources)
    options = speech.default_options("fake", "en")
    first = await speech.synthesize_text(VOICE, TEXT, options, user_id=env.users[0])

    second = await speech.synthesize_text(VOICE, "  " + TEXT + "  ", options, user_id=env.users[0])
    third = await speech.synthesize_text(VOICE, TEXT, options, user_id=env.users[1])

    assert not first.cache_hit
    assert second.cache_hit
    assert third.cache_hit
    assert second.audio == first.audio
    assert second.words == first.words
    assert await env.count("SELECT hit_count FROM tts_cache") == 2
    assert await env.count("SELECT count(*) FROM usage_records") == 1
    row = await env.count("SELECT count(*) FROM tts_cache WHERE last_used_at >= created_at")
    assert row == 1


async def test_the_usage_record_has_the_tts_shape(env: Env) -> None:
    speech = speech_for(env.resources)
    await speech.synthesize_text(VOICE, TEXT, speech.default_options("fake", "en"), user_id=env.users[0])

    async with env.database.transaction() as session:
        row = (
            await session.execute(
                text(
                    "SELECT user_id, stage, provider, model, audio_characters, cost_micros_usd, credits, job_id "
                    "FROM usage_records"
                )
            )
        ).one()

    assert tuple(row) == (env.users[0], "tts", "fake", "fake-tts-1", len(TEXT), 0, 0, None)


async def test_deleting_a_voices_cache_removes_rows_assets_and_objects(env: Env) -> None:
    speech = speech_for(env.resources)
    options = speech.default_options("fake", "en")
    for sentence in ("One.", "Two."):
        await speech.synthesize_text(VOICE, sentence, options, user_id=env.users[0])
    await speech.synthesize_text(VoiceRef("fake", "fake-voice-bram", "en"), "Three.", options, user_id=env.users[0])
    keys = await asset_keys(env, "tts/%")
    assert len(keys) == 3

    deleted = await speech.delete_cache_for_voice("fake", "fake-voice-aria")

    assert deleted == 2
    assert await env.count("SELECT count(*) FROM tts_cache") == 1
    remaining = await asset_keys(env, "tts/%")
    assert len(remaining) == 1
    assert [await env.storage.exists(key) for key in keys].count(True) == 1


async def test_pruning_removes_entries_unused_for_ninety_days(env: Env) -> None:
    speech = speech_for(env.resources)
    options = speech.default_options("fake", "en")
    await speech.synthesize_text(VOICE, "Old.", options, user_id=env.users[0])
    await speech.synthesize_text(VOICE, "Fresh.", options, user_id=env.users[0])
    async with env.database.transaction() as session:
        await session.execute(
            text("UPDATE tts_cache SET last_used_at = now() - interval '91 days' WHERE characters = 4")
        )

    pruned = await prune_unused_tts_cache(speech, env.resources.clock)

    assert pruned == 1
    assert await env.count("SELECT count(*) FROM tts_cache") == 1
    assert await env.count("SELECT count(*) FROM tts_cache WHERE characters = 6") == 1
    assert len(await asset_keys(env, "tts/%")) == 1


async def test_assets_are_stored_with_hash_size_and_owner_scoping(env: Env) -> None:
    assets = assets_for(env.resources)
    owner, other = env.users
    key = f"media/u/{owner}/x/file.bin"

    async with env.database.transaction() as session:
        stored = await assets.store_chunks(
            session,
            one_chunk(VIDEO_BYTES),
            AssetSpec(
                key=key, kind=AssetKind.VIDEO, content_type="video/mp4", owner_user_id=owner, width=64, height=64
            ),
        )

    assert stored.status is AssetStatus.READY
    assert stored.size_bytes == len(VIDEO_BYTES)
    assert stored.sha256 is not None
    assert await assets.read_bytes(stored) == VIDEO_BYTES
    async with env.database.transaction() as session:
        assert (await assets.get(session, owner, stored.id)).storage_key == key
        with pytest.raises(AssetNotFoundError):
            await assets.get(session, other, stored.id)
        with pytest.raises(AssetNotFoundError):
            await assets.get(session, None, stored.id)
    info = await env.storage.head(key)
    assert info is not None
    assert info.content_type == "video/mp4"


async def test_a_duplicate_key_is_a_conflict_and_leaves_the_first_object_intact(env: Env) -> None:
    assets = assets_for(env.resources)
    spec = AssetSpec(key="tts/zz/duplicate.mp3", kind=AssetKind.AUDIO, content_type="audio/mpeg")
    async with env.database.transaction() as session:
        await assets.store_bytes(session, b"first", spec)

    with pytest.raises(AssetKeyExistsError):
        async with env.database.transaction() as session:
            await assets.store_bytes(session, b"second", spec)

    async with env.database.transaction() as session:
        found = await assets.find_by_key(session, None, spec.key)
    assert found is not None
    assert await assets.read_bytes(found) == b"first"


async def test_a_rolled_back_transaction_removes_the_uploaded_object(env: Env) -> None:
    assets = assets_for(env.resources)
    spec = AssetSpec(key="tts/zz/rolled-back.mp3", kind=AssetKind.AUDIO, content_type="audio/mpeg")

    async def store_then_abort() -> None:
        async with env.database.transaction() as session:
            await assets.store_bytes(session, b"payload", spec)
            raise RuntimeError("abort")

    with pytest.raises(RuntimeError, match="abort"):
        await store_then_abort()

    assert not await env.storage.exists(spec.key)
    assert await env.count("SELECT count(*) FROM assets WHERE storage_key = 'tts/zz/rolled-back.mp3'") == 0


async def test_deleting_an_asset_removes_the_row_and_the_object(env: Env) -> None:
    assets = assets_for(env.resources)
    async with env.database.transaction() as session:
        stored = await assets.store_bytes(
            session, b"x", AssetSpec(key="tts/zz/delete-me.mp3", kind=AssetKind.AUDIO, content_type="audio/mpeg")
        )

    async with env.database.transaction() as session:
        await assets.delete(session, None, stored.id)

    assert not await env.storage.exists("tts/zz/delete-me.mp3")
    assert await env.count("SELECT count(*) FROM assets WHERE storage_key = 'tts/zz/delete-me.mp3'") == 0


async def test_an_asset_used_by_a_render_cannot_be_deleted(media_api: MediaApi) -> None:
    render_id = await media_api.seed_render(media_api.primary_id)
    assets = assets_for(media_api.resources)
    async with media_api.database.transaction() as session:
        composition = (
            await session.execute(text("SELECT composition_asset_id FROM renders WHERE id = :id"), {"id": render_id})
        ).scalar_one()

    with pytest.raises(AssetInUseError):
        async with media_api.database.transaction() as session:
            await assets.delete(session, media_api.primary_id, composition)

    assert await media_api.storage.exists(f"media/u/{media_api.primary_id}/renders/{render_id}/16x9.mp4")


async def test_deleting_by_prefix_matches_literally_and_per_owner(env: Env) -> None:
    owner, other = env.users
    assets = assets_for(env.resources)
    keys = {
        "a_b/one.bin": owner,
        "a_b/two.bin": owner,
        "axb/three.bin": owner,
        "a_b/four.bin": other,
    }
    async with env.database.transaction() as session:
        for key, user in keys.items():
            await assets.store_bytes(
                session, b"x", AssetSpec(key=key, kind=AssetKind.AUDIO, content_type="audio/mpeg", owner_user_id=user)
            )

    async with env.database.transaction() as session:
        removed = await assets.delete_by_prefix(session, owner, "a_b/")

    assert removed == 2
    assert await asset_keys(env, "a%b/%") == ["a_b/four.bin", "axb/three.bin"]
    assert not await env.storage.exists("a_b/one.bin")
    assert await env.storage.exists("a_b/four.bin")
    assert await env.storage.exists("axb/three.bin")


async def test_the_repository_reports_key_collisions_and_references(env: Env) -> None:
    async with env.database.transaction() as session:
        repository = SqlAssetRepository(session)
        row = NewAssetRow(None, "audio", "tts/zz/repo.mp3", "audio/mpeg", None, None, None, {})
        pending = await repository.insert_pending(row)
        assert pending.status == "pending"
        assert pending.sha256 is None
        with pytest.raises(AssetKeyTakenError):
            await repository.insert_pending(row)
        ready = await repository.mark_ready(pending.id, sha256=bytes(32), size_bytes=7)
        assert (ready.status, ready.size_bytes) == ("ready", 7)
        assert await repository.get(env.users[0], pending.id) is None
        assert (await repository.get(None, pending.id)) is not None
        assert (await repository.get_by_key(None, "tts/zz/repo.mp3")) is not None
        assert await repository.delete(env.users[0], pending.id) is False
        assert await repository.delete(None, pending.id) is True
        assert await repository.delete(None, pending.id) is False


async def test_a_referenced_asset_raises_a_reference_error_in_the_repository(media_api: MediaApi) -> None:
    render_id = await media_api.seed_render(media_api.primary_id)

    async with media_api.database.transaction() as session:
        composition = (
            await session.execute(text("SELECT composition_asset_id FROM renders WHERE id = :id"), {"id": render_id})
        ).scalar_one()
        with pytest.raises(AssetReferencedError):
            await SqlAssetRepository(session).delete(media_api.primary_id, composition)


async def test_purging_a_deleted_user_removes_their_media_and_nothing_else(media_api: MediaApi) -> None:
    resources = media_api.resources
    doomed, keeper = await create_users(resources.database, 2)
    deleted_at = resources.clock.now() - timedelta(days=31)
    async with resources.database.transaction() as session:
        await session.execute(
            text("UPDATE users SET status = 'deleted', deleted_at = :at WHERE id = :id"),
            {"at": deleted_at, "id": doomed},
        )
    doomed_render = await media_api.seed_render(doomed, aspects=("16:9", "9:16"))
    keeper_render = await media_api.seed_render(keeper)
    extra = [
        f"work/renders/{doomed_render}/audio.wav",
        f"voice/u/{doomed}/v1/sample-0.wav",
        f"voice/u/{keeper}/v1/sample-0.wav",
        f"work/renders/{keeper_render}/audio.wav",
    ]
    for key in extra:
        await media_api.put_object(key, b"x", "application/octet-stream")
    try:
        purged = await purge_expired_users(resources)

        assert purged == 1
        assert await count_users(media_api, doomed) == 0
        assert await count_users(media_api, keeper) == 1
        for key in (extra[0], extra[1]):
            assert not await media_api.storage.exists(key)
        assert not await media_api.storage.exists(f"media/u/{doomed}/renders/{doomed_render}/16x9.mp4")
        assert not await media_api.storage.exists(f"media/u/{doomed}/renders/{doomed_render}/9x16.mp4")
        for key in (extra[2], extra[3], f"media/u/{keeper}/renders/{keeper_render}/16x9.mp4"):
            assert await media_api.storage.exists(key)
        async with resources.database.transaction() as session:
            remaining = (
                await session.execute(text("SELECT count(*) FROM renders WHERE owner_user_id = :id"), {"id": doomed})
            ).scalar_one()
            assets = (
                await session.execute(text("SELECT count(*) FROM assets WHERE owner_user_id = :id"), {"id": doomed})
            ).scalar_one()
        assert (remaining, assets) == (0, 0)
    finally:
        await purge_media_data(resources.database, [doomed, keeper])


async def count_users(media_api: MediaApi, user_id: UUID) -> int:
    async with media_api.database.transaction() as session:
        return (await session.execute(text("SELECT count(*) FROM users WHERE id = :id"), {"id": user_id})).scalar_one()
