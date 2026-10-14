import asyncio
import re
from datetime import timedelta
from urllib.parse import unquote, urlsplit
from uuid import UUID

from redis.asyncio import Redis

from motionile.core.config import RedisSettings

NAMESPACE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
PART_PATTERN = re.compile(r"^[A-Za-z0-9_.@+=/-]{1,200}$")
DEFAULT_REDIS_PORT = 6379

type KeyPart = str | int | UUID


class MissingTTLError(ValueError):
    def __init__(self) -> None:
        super().__init__("every Redis write needs a positive TTL")


def create_redis_client(settings: RedisSettings) -> Redis:
    parts = urlsplit(settings.url)
    database = parts.path.lstrip("/")
    return Redis(
        host=parts.hostname or "localhost",
        port=parts.port or DEFAULT_REDIS_PORT,
        db=int(database) if database else 0,
        username=unquote(parts.username) if parts.username else None,
        password=unquote(parts.password) if parts.password else None,
        ssl=parts.scheme == "rediss",
        socket_timeout=settings.socket_timeout_seconds,
        socket_connect_timeout=settings.socket_timeout_seconds,
        health_check_interval=30,
    )


class RedisKeyBuilder:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    def key(self, namespace: str, *parts: KeyPart) -> str:
        if not NAMESPACE_PATTERN.match(namespace):
            message = f"invalid Redis key namespace {namespace!r}"
            raise ValueError(message)
        if not parts:
            message = "a Redis key needs at least one part after the namespace"
            raise ValueError(message)
        rendered = [str(part) for part in parts]
        for part in rendered:
            if not PART_PATTERN.match(part):
                message = f"invalid Redis key part {part!r}"
                raise ValueError(message)
        return ":".join([self.prefix, namespace, *rendered])


def _ttl_milliseconds(ttl: timedelta) -> int:
    milliseconds = int(ttl.total_seconds() * 1000)
    if milliseconds <= 0:
        raise MissingTTLError
    return milliseconds


class RedisStore:
    def __init__(self, client: Redis, keys: RedisKeyBuilder) -> None:
        self.client = client
        self.keys = keys

    async def set(self, key: str, value: bytes | str, *, ttl: timedelta) -> None:
        await self.client.set(key, value, px=_ttl_milliseconds(ttl))

    async def set_if_absent(self, key: str, value: bytes | str, *, ttl: timedelta) -> bool:
        stored = await self.client.set(key, value, px=_ttl_milliseconds(ttl), nx=True)
        return bool(stored)

    async def get(self, key: str) -> bytes | None:
        value = await self.client.get(key)
        if isinstance(value, str):
            return value.encode()
        return value

    async def delete(self, key: str) -> None:
        await self.client.delete(key)

    async def increment(self, key: str, *, ttl: timedelta) -> int:
        milliseconds = _ttl_milliseconds(ttl)
        async with self.client.pipeline(transaction=True) as pipeline:
            pipeline.incr(key)
            pipeline.pexpire(key, milliseconds, nx=True)
            count, _ = await pipeline.execute()
        return int(count)

    async def ping(self, timeout_seconds: float) -> None:
        async with asyncio.timeout(timeout_seconds):
            await self.client.get(self.keys.key("health", "probe"))
