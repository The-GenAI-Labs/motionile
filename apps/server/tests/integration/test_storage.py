from collections.abc import AsyncIterator
from datetime import timedelta

import httpx
import pytest

from motionile.core.config import Settings
from motionile.core.storage.base import ObjectNotFoundError
from motionile.core.storage.s3 import S3Storage

LARGE_OBJECT_BYTES = 9 * 1024 * 1024


async def chunks_of(data: bytes, size: int = 256 * 1024) -> AsyncIterator[bytes]:
    for start in range(0, len(data), size):
        yield data[start : start + size]


@pytest.fixture
async def storage(settings: Settings) -> S3Storage:
    s3 = S3Storage.from_settings(settings.storage)
    await s3.ensure_bucket()
    await s3.ensure_bucket()
    return s3


async def test_round_trips_objects_with_metadata(storage: S3Storage) -> None:
    info = await storage.put(
        "tests/hello.txt", chunks_of(b"hello minio"), content_type="text/plain", metadata={"owner": "tests"}
    )
    data = b"".join([chunk async for chunk in storage.get("tests/hello.txt", chunk_size=4)])

    assert info.size_bytes == 11
    assert info.content_type == "text/plain"
    assert info.metadata == {"owner": "tests"}
    assert info.etag
    assert data == b"hello minio"


async def test_streams_large_objects_through_a_spool(storage: S3Storage) -> None:
    payload = bytes(range(256)) * (LARGE_OBJECT_BYTES // 256)

    info = await storage.put("tests/large.bin", chunks_of(payload), content_type="application/octet-stream")
    received = b"".join([chunk async for chunk in storage.get("tests/large.bin")])

    assert info.size_bytes == LARGE_OBJECT_BYTES
    assert received == payload


async def test_missing_objects(storage: S3Storage) -> None:
    assert await storage.head("tests/missing.txt") is None
    assert not await storage.exists("tests/missing.txt")
    with pytest.raises(ObjectNotFoundError):
        [chunk async for chunk in storage.get("tests/missing.txt")]


async def test_delete_is_idempotent(storage: S3Storage) -> None:
    await storage.put("tests/delete-me.txt", chunks_of(b"x"), content_type="text/plain")

    await storage.delete("tests/delete-me.txt")
    await storage.delete("tests/delete-me.txt")

    assert not await storage.exists("tests/delete-me.txt")


async def test_presigned_urls_work_and_expire_scope(storage: S3Storage) -> None:
    put_url = await storage.presigned_put_url(
        "tests/presigned.txt", content_type="text/plain", expires_in=timedelta(minutes=5)
    )
    async with httpx.AsyncClient() as http:
        uploaded = await http.put(put_url, content=b"via presign", headers={"Content-Type": "text/plain"})
        wrong_type = await http.put(put_url, content=b"x", headers={"Content-Type": "image/png"})
        get_url = await storage.presigned_get_url(
            "tests/presigned.txt", expires_in=timedelta(minutes=5), download_filename="report.txt"
        )
        downloaded = await http.get(get_url)
        tampered = await http.get(get_url.replace("presigned.txt", "hello.txt"))

    assert uploaded.status_code == 200
    assert wrong_type.status_code == 403
    assert downloaded.content == b"via presign"
    assert downloaded.headers["content-disposition"] == 'attachment; filename="report.txt"'
    assert tampered.status_code == 403
