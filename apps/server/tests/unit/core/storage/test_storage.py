from collections.abc import AsyncIterator
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import SecretStr
from tests.fakes.storage import InMemoryStorage

from motionile.core.config import StorageSettings
from motionile.core.storage.base import InvalidStorageKeyError, ObjectNotFoundError, Storage, validate_key
from motionile.core.storage.s3 import S3Storage


async def chunks_of(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


@pytest.mark.parametrize(
    "key",
    ["videos/2026/abc.mp4", "users/01920000-0000-7000-8000-000000000001/avatar.png", "a", "thumbs/x_y-z.(1).jpg"],
)
def test_accepts_safe_keys(key: str) -> None:
    assert validate_key(key) == key


@pytest.mark.parametrize(
    "key",
    ["", "/leading", "trailing/", "double//slash", "../escape", "a/../b", "space here", "back\\slash", "a" * 1025, "é"],
)
def test_rejects_unsafe_keys(key: str) -> None:
    with pytest.raises(InvalidStorageKeyError):
        validate_key(key)


async def test_in_memory_storage_round_trips_and_satisfies_protocol() -> None:
    storage = InMemoryStorage()

    info = await storage.put("a/b.txt", chunks_of(b"hello ", b"world"), content_type="text/plain", metadata={"k": "v"})
    collected = [chunk async for chunk in storage.get("a/b.txt", chunk_size=4)]

    assert isinstance(storage, Storage)
    assert info.size_bytes == 11
    assert info.metadata == {"k": "v"}
    assert b"".join(collected) == b"hello world"
    assert collected[0] == b"hell"
    assert await storage.exists("a/b.txt")
    await storage.delete("a/b.txt")
    assert not await storage.exists("a/b.txt")
    with pytest.raises(ObjectNotFoundError):
        [chunk async for chunk in storage.get("a/b.txt")]


def make_s3_storage() -> S3Storage:
    settings = StorageSettings(
        endpoint_url="http://localhost:9000",
        bucket="motionile-test",
        access_key_id=SecretStr("motionile"),
        secret_access_key=SecretStr("motionile-dev-secret"),
        force_path_style=True,
    )
    return S3Storage.from_settings(settings)


async def test_s3_presigned_get_url_sanitizes_download_filename() -> None:
    url = await make_s3_storage().presigned_get_url(
        "videos/a.mp4", expires_in=timedelta(minutes=5), download_filename='evil"\r\nname.mp4'
    )
    parts = urlsplit(url)
    query = parse_qs(parts.query)

    assert parts.path == "/motionile-test/videos/a.mp4"
    assert query["X-Amz-Expires"] == ["300"]
    assert query["response-content-disposition"] == ['attachment; filename="evilname.mp4"']


async def test_s3_presigned_put_url_signs_content_type() -> None:
    url = await make_s3_storage().presigned_put_url(
        "uploads/a.png", content_type="image/png", expires_in=timedelta(minutes=1)
    )

    assert "content-type" in parse_qs(urlsplit(url).query)["X-Amz-SignedHeaders"][0]


async def test_s3_storage_validates_keys_before_any_call() -> None:
    with pytest.raises(InvalidStorageKeyError):
        await make_s3_storage().presigned_get_url("../etc/passwd", expires_in=timedelta(minutes=1))
