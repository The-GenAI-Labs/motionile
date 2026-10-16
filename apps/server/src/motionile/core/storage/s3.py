import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Mapping
from datetime import timedelta
from tempfile import SpooledTemporaryFile
from typing import TYPE_CHECKING, cast

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from motionile.core.config import StorageSettings
from motionile.core.storage.base import DEFAULT_CHUNK_SIZE, ObjectInfo, ObjectNotFoundError, validate_key

if TYPE_CHECKING:
    from types_boto3_s3.client import S3Client
    from types_boto3_s3.type_defs import ObjectIdentifierTypeDef

SPOOL_MAX_MEMORY_BYTES = 8 * 1024 * 1024
NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NotFound"})


def is_not_found(error: ClientError) -> bool:
    code = str(error.response.get("Error", {}).get("Code", ""))
    return code in NOT_FOUND_CODES


def create_s3_client(settings: StorageSettings) -> "S3Client":
    config = Config(
        signature_version="s3v4",
        s3={"addressing_style": "path" if settings.force_path_style else "virtual"},
        retries={"max_attempts": 3, "mode": "standard"},
        connect_timeout=5,
        read_timeout=60,
    )
    access_key = settings.access_key_id.get_secret_value() if settings.access_key_id else None
    secret_key = settings.secret_access_key.get_secret_value() if settings.secret_access_key else None
    client: S3Client = boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        region_name=settings.region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=config,
    )
    return client


class S3Storage:
    def __init__(self, client: "S3Client", bucket: str) -> None:
        self.client = client
        self.bucket = bucket

    @classmethod
    def from_settings(cls, settings: StorageSettings) -> "S3Storage":
        return cls(create_s3_client(settings), settings.bucket)

    async def ensure_bucket(self) -> None:
        try:
            await asyncio.to_thread(self.client.head_bucket, Bucket=self.bucket)
        except ClientError as error:
            if not is_not_found(error):
                raise
            await asyncio.to_thread(self.client.create_bucket, Bucket=self.bucket)

    async def put(
        self,
        key: str,
        chunks: AsyncIterable[bytes],
        *,
        content_type: str,
        metadata: Mapping[str, str] | None = None,
    ) -> ObjectInfo:
        validate_key(key)
        with SpooledTemporaryFile(max_size=SPOOL_MAX_MEMORY_BYTES) as spool:
            async for chunk in chunks:
                await asyncio.to_thread(spool.write, chunk)
            await asyncio.to_thread(spool.seek, 0)
            await asyncio.to_thread(
                self.client.upload_fileobj,
                spool,
                self.bucket,
                key,
                ExtraArgs={"ContentType": content_type, "Metadata": dict(metadata or {})},
            )
        info = await self.head(key)
        if info is None:
            raise ObjectNotFoundError(key)
        return info

    async def get(self, key: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> AsyncIterator[bytes]:
        validate_key(key)
        try:
            response = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket, Key=key)
        except ClientError as error:
            if is_not_found(error):
                raise ObjectNotFoundError(key) from error
            raise
        body = response["Body"]
        try:
            while True:
                chunk = await asyncio.to_thread(body.read, chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(body.close)

    async def delete(self, key: str) -> None:
        validate_key(key)
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)

    async def delete_prefix(self, prefix: str) -> None:
        validate_key(prefix.rstrip("/"))
        continuation: str | None = None
        while True:
            if continuation is None:
                response = await asyncio.to_thread(self.client.list_objects_v2, Bucket=self.bucket, Prefix=prefix)
            else:
                response = await asyncio.to_thread(
                    self.client.list_objects_v2,
                    Bucket=self.bucket,
                    Prefix=prefix,
                    ContinuationToken=continuation,
                )
            keys: list[ObjectIdentifierTypeDef] = [
                {"Key": key} for item in response.get("Contents", []) if (key := item.get("Key")) is not None
            ]
            if keys:
                await asyncio.to_thread(self.client.delete_objects, Bucket=self.bucket, Delete={"Objects": keys})
            if not response.get("IsTruncated"):
                return
            continuation = str(response["NextContinuationToken"])

    async def head(self, key: str) -> ObjectInfo | None:
        validate_key(key)
        try:
            response = await asyncio.to_thread(self.client.head_object, Bucket=self.bucket, Key=key)
        except ClientError as error:
            if is_not_found(error):
                return None
            raise
        return ObjectInfo(
            key=key,
            size_bytes=int(response.get("ContentLength", 0)),
            content_type=response.get("ContentType"),
            etag=cast("str | None", response.get("ETag")),
            last_modified=response.get("LastModified"),
            metadata=dict(response.get("Metadata", {})),
        )

    async def exists(self, key: str) -> bool:
        return await self.head(key) is not None

    async def presigned_get_url(self, key: str, *, expires_in: timedelta, download_filename: str | None = None) -> str:
        validate_key(key)
        params: dict[str, str] = {"Bucket": self.bucket, "Key": key}
        if download_filename is not None:
            safe_name = "".join(
                character for character in download_filename if character.isalnum() or character in "._-"
            )
            params["ResponseContentDisposition"] = f'attachment; filename="{safe_name or "download"}"'
        return await asyncio.to_thread(
            self.client.generate_presigned_url,
            "get_object",
            Params=params,
            ExpiresIn=int(expires_in.total_seconds()),
        )

    async def presigned_put_url(self, key: str, *, content_type: str, expires_in: timedelta) -> str:
        validate_key(key)
        return await asyncio.to_thread(
            self.client.generate_presigned_url,
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=int(expires_in.total_seconds()),
        )
