from datetime import timedelta
from urllib.parse import urlsplit

import pytest
from pydantic import SecretStr, ValidationError

from motionile.core.config import StorageSettings
from motionile.core.storage.s3 import S3Storage


def storage_with(public_endpoint_url: str | None) -> S3Storage:
    return S3Storage.from_settings(
        StorageSettings(
            endpoint_url="http://minio:9000",
            public_endpoint_url=public_endpoint_url,
            bucket="motionile-test",
            access_key_id=SecretStr("motionile"),
            secret_access_key=SecretStr("motionile-dev-secret"),
        )
    )


async def test_presigned_urls_target_the_public_endpoint_when_set() -> None:
    storage = storage_with("http://localhost:9000")

    get_url = await storage.presigned_get_url("media/u/a/video.mp4", expires_in=timedelta(minutes=5))
    put_url = await storage.presigned_put_url(
        "uploads/a.png", content_type="image/png", expires_in=timedelta(minutes=5)
    )

    assert urlsplit(get_url).netloc == "localhost:9000"
    assert urlsplit(put_url).netloc == "localhost:9000"
    assert urlsplit(get_url).path == "/motionile-test/media/u/a/video.mp4"


async def test_presigned_urls_use_the_internal_endpoint_by_default() -> None:
    storage = storage_with(None)

    url = await storage.presigned_get_url("media/u/a/video.mp4", expires_in=timedelta(minutes=5))

    assert urlsplit(url).netloc == "minio:9000"
    assert storage.presign_client is storage.client


def test_the_api_client_keeps_the_internal_endpoint() -> None:
    storage = storage_with("http://localhost:9000")

    assert storage.client.meta.endpoint_url == "http://minio:9000"
    assert storage.presign_client.meta.endpoint_url == "http://localhost:9000"
    assert storage.presign_client is not storage.client


def test_a_blank_public_endpoint_means_unset() -> None:
    assert StorageSettings(public_endpoint_url="").public_endpoint_url is None


def test_the_public_endpoint_loses_its_trailing_slash() -> None:
    assert StorageSettings(public_endpoint_url="https://files.example.com/").public_endpoint_url == (
        "https://files.example.com"
    )


@pytest.mark.parametrize(
    "value",
    [
        "ftp://files.example.com",
        "files.example.com",
        "https://user:secret@files.example.com",
        "https://files.example.com/bucket",
        "https://files.example.com?x=1",
        "https://files.example.com#frag",
    ],
)
def test_the_public_endpoint_must_be_an_origin(value: str) -> None:
    with pytest.raises(ValidationError):
        StorageSettings(public_endpoint_url=value)
