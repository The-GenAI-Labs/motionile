import hashlib
from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from tests.fakes.media import World, fake_session
from tests.fakes.storage import InMemoryStorage
from tests.unit.modules.media.support import USER_A, USER_B

from motionile.core.db import run_after_commit, run_after_rollback
from motionile.core.storage.base import InvalidStorageKeyError, ObjectNotFoundError
from motionile.modules.media import (
    AssetInUseError,
    AssetKeyExistsError,
    AssetKind,
    AssetNotFoundError,
    AssetService,
    AssetSpec,
    AssetStatus,
    AssetTooLargeError,
)

PAYLOAD = b"narration bytes " * 100


def spec(
    key: str = "tts/ab/abc.mp3",
    *,
    owner: UUID | None = None,
    duration_ms: int | None = None,
    width: int | None = None,
    height: int | None = None,
) -> AssetSpec:
    return AssetSpec(
        key=key,
        kind=AssetKind.AUDIO,
        content_type="audio/mpeg",
        owner_user_id=owner,
        duration_ms=duration_ms,
        width=width,
        height=height,
    )


def build() -> tuple[AssetService, InMemoryStorage, World]:
    world = World()
    storage = InMemoryStorage()
    return AssetService(storage, world.asset_store), storage, world


async def chunked(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


async def test_storing_bytes_records_hash_size_and_metadata() -> None:
    service, storage, _ = build()
    session = fake_session()

    view = await service.store_bytes(session, PAYLOAD, spec(owner=USER_A, duration_ms=1500, width=640, height=360))

    assert view.status is AssetStatus.READY
    assert view.kind is AssetKind.AUDIO
    assert view.size_bytes == len(PAYLOAD)
    assert view.sha256 == hashlib.sha256(PAYLOAD).digest()
    assert view.sha256_hex == hashlib.sha256(PAYLOAD).hexdigest()
    assert (view.duration_ms, view.width, view.height) == (1500, 640, 360)
    assert view.content_type == "audio/mpeg"
    assert storage.objects["tts/ab/abc.mp3"].data == PAYLOAD
    assert storage.objects["tts/ab/abc.mp3"].content_type == "audio/mpeg"


async def test_storing_chunks_hashes_the_whole_stream() -> None:
    service, storage, _ = build()

    view = await service.store_chunks(fake_session(), chunked(b"one ", b"two ", b"three"), spec())

    assert view.size_bytes == len(b"one two three")
    assert view.sha256 == hashlib.sha256(b"one two three").digest()
    assert storage.objects["tts/ab/abc.mp3"].data == b"one two three"


async def test_a_second_asset_with_the_same_key_is_rejected_without_touching_storage() -> None:
    service, storage, _ = build()
    session = fake_session()
    await service.store_bytes(session, b"first", spec())

    with pytest.raises(AssetKeyExistsError):
        await service.store_bytes(session, b"second", spec())

    assert storage.objects["tts/ab/abc.mp3"].data == b"first"


async def test_oversized_streams_are_refused_and_leave_nothing_behind() -> None:
    service, storage, _ = build()

    with pytest.raises(AssetTooLargeError):
        await service.store_chunks(fake_session(), chunked(b"x" * 10, b"y" * 10), spec(), max_bytes=15)

    assert storage.objects == {}


async def test_invalid_keys_are_refused_before_any_row_is_written() -> None:
    service, _, world = build()

    with pytest.raises(InvalidStorageKeyError):
        await service.store_bytes(fake_session(), b"x", spec("../escape"))

    assert world.assets == {}


async def test_the_object_is_removed_when_the_transaction_rolls_back() -> None:
    service, storage, _ = build()
    session = fake_session()
    await service.store_bytes(session, b"payload", spec())

    await run_after_rollback(session)

    assert "tts/ab/abc.mp3" not in storage.objects


async def test_the_object_stays_when_the_transaction_commits() -> None:
    service, storage, _ = build()
    session = fake_session()
    await service.store_bytes(session, b"payload", spec())

    await run_after_commit(session)
    await run_after_rollback(session)

    assert "tts/ab/abc.mp3" in storage.objects


async def test_reads_are_scoped_to_the_owner() -> None:
    service, _, _ = build()
    session = fake_session()
    stored = await service.store_bytes(session, b"mine", spec("media/u/a/x.mp3", owner=USER_A))

    assert (await service.get(session, USER_A, stored.id)).storage_key == "media/u/a/x.mp3"
    with pytest.raises(AssetNotFoundError):
        await service.get(session, USER_B, stored.id)
    with pytest.raises(AssetNotFoundError):
        await service.get(session, None, stored.id)


async def test_system_assets_have_no_owner() -> None:
    service, _, _ = build()
    session = fake_session()
    stored = await service.store_bytes(session, b"system", spec())

    assert stored.owner_user_id is None
    assert (await service.get(session, None, stored.id)).id == stored.id
    with pytest.raises(AssetNotFoundError):
        await service.get(session, USER_A, stored.id)


async def test_assets_are_found_by_key_within_their_owner_scope() -> None:
    service, _, _ = build()
    session = fake_session()
    stored = await service.store_bytes(session, b"x", spec("media/u/a/x.mp3", owner=USER_A))

    found = await service.find_by_key(session, USER_A, "media/u/a/x.mp3")

    assert found is not None
    assert found.id == stored.id
    assert await service.find_by_key(session, USER_B, "media/u/a/x.mp3") is None
    assert await service.find_by_key(session, USER_A, "media/u/a/missing.mp3") is None


async def test_reading_streams_the_stored_bytes() -> None:
    service, _, _ = build()
    session = fake_session()
    stored = await service.store_bytes(session, PAYLOAD, spec())

    assert await service.read_bytes(stored) == PAYLOAD
    assert b"".join([chunk async for chunk in service.read(stored, chunk_size=64)]) == PAYLOAD


async def test_deleting_removes_the_row_and_the_object_after_commit() -> None:
    service, storage, world = build()
    session = fake_session()
    stored = await service.store_bytes(session, b"x", spec())
    await run_after_commit(session)

    deleting = fake_session()
    await service.delete(deleting, None, stored.id)
    assert world.assets == {}
    assert "tts/ab/abc.mp3" in storage.objects
    await run_after_commit(deleting)

    assert "tts/ab/abc.mp3" not in storage.objects


async def test_a_rolled_back_delete_keeps_the_object() -> None:
    service, storage, _ = build()
    session = fake_session()
    stored = await service.store_bytes(session, b"x", spec())
    await run_after_commit(session)

    deleting = fake_session()
    await service.delete(deleting, None, stored.id)
    await run_after_rollback(deleting)

    assert "tts/ab/abc.mp3" in storage.objects


async def test_deleting_a_foreign_asset_is_not_found() -> None:
    service, _, _ = build()
    session = fake_session()
    stored = await service.store_bytes(session, b"x", spec("media/u/a/x.mp3", owner=USER_A))

    with pytest.raises(AssetNotFoundError):
        await service.delete(session, USER_B, stored.id)


async def test_deleting_a_referenced_asset_is_a_conflict() -> None:
    service, storage, world = build()
    session = fake_session()
    stored = await service.store_bytes(session, b"x", spec())
    world.referenced.add(stored.id)

    with pytest.raises(AssetInUseError):
        await service.delete(session, None, stored.id)
    await run_after_commit(session)

    assert "tts/ab/abc.mp3" in storage.objects


async def test_deleting_by_prefix_removes_only_the_owners_matching_assets() -> None:
    service, storage, world = build()
    session = fake_session()
    await service.store_bytes(session, b"1", spec("voice/u/a/v1/sample-0.wav", owner=USER_A))
    await service.store_bytes(session, b"2", spec("voice/u/a/v1/sample-1.wav", owner=USER_A))
    await service.store_bytes(session, b"3", spec("voice/u/a/v2/sample-0.wav", owner=USER_A))
    await service.store_bytes(session, b"4", spec("voice/u/a/v1/sample-9.wav", owner=USER_B))
    await run_after_commit(session)

    deleting = fake_session()
    count = await service.delete_by_prefix(deleting, USER_A, "voice/u/a/v1/")
    await run_after_commit(deleting)

    assert count == 2
    assert sorted(storage.objects) == [
        "voice/u/a/v1/sample-9.wav",
        "voice/u/a/v2/sample-0.wav",
    ]
    assert len(world.assets) == 2


async def test_deleting_by_prefix_validates_the_prefix() -> None:
    service, _, _ = build()

    with pytest.raises(InvalidStorageKeyError):
        await service.delete_by_prefix(fake_session(), USER_A, "../")


async def test_storage_failures_discard_the_partial_upload() -> None:
    service, storage, _ = build()

    class Broken:
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"partial"
            raise ConnectionError("stream broke")

    with pytest.raises(ConnectionError):
        await service.store_chunks(fake_session(), Broken(), spec())

    assert storage.objects == {}


async def test_reading_a_missing_object_raises() -> None:
    service, storage, _ = build()
    stored = await service.store_bytes(fake_session(), b"x", spec())
    del storage.objects[stored.storage_key]

    with pytest.raises(ObjectNotFoundError):
        await service.read_bytes(stored)
