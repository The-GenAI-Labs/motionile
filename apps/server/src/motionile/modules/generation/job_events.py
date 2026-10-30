import json
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Final, Protocol, Self, cast
from uuid import UUID

import anyio
import structlog
from pydantic import JsonValue
from redis.exceptions import RedisError

from motionile.core.redis import RedisKeyBuilder, RedisStore
from motionile.core.schemas import ResponseModel

CHANNEL_NAMESPACE: Final = "job"
TERMINAL_EVENT_TYPES: Final = frozenset({"job.completed", "job.failed", "job.cancelled"})

logger = structlog.get_logger(__name__)


def job_channel(keys: RedisKeyBuilder, job_id: UUID) -> str:
    return keys.key(CHANNEL_NAMESPACE, job_id)


class JobMessage(ResponseModel):
    id: UUID | None
    type: str
    stage: str | None
    payload: dict[str, JsonValue]
    at: datetime

    @property
    def is_terminal(self) -> bool:
        return self.type in TERMINAL_EVENT_TYPES

    def to_json(self) -> str:
        document: dict[str, Any] = self.model_dump(mode="json", by_alias=True)
        return json.dumps(document, separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: bytes | str) -> Self | None:
        try:
            return cls.model_validate_json(raw)
        except ValueError:
            return None


type Polled = Mapping[str, object] | None


class PubSubLike(Protocol):
    async def subscribe(self, channel: str) -> None: ...

    async def unsubscribe(self, channel: str) -> None: ...

    async def aclose(self) -> None: ...

    async def get_message(self, *, ignore_subscribe_messages: bool, timeout: float) -> Polled: ...  # noqa: ASYNC109


class PublishingClient(Protocol):
    async def publish(self, channel: str, message: str) -> int: ...

    def pubsub(self) -> PubSubLike: ...


class JobSubscription:
    def __init__(self, pubsub: PubSubLike) -> None:
        self._pubsub = pubsub

    async def next(self, timeout_seconds: float) -> JobMessage | None:
        message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=timeout_seconds)
        if message is None:
            return None
        data = message.get("data")
        if not isinstance(data, bytes | str):
            return None
        return JobMessage.from_json(data)


class JobEvents:
    def __init__(self, store: RedisStore) -> None:
        self._store = store

    def _client(self) -> PublishingClient:
        return cast("PublishingClient", self._store.client)

    def channel(self, job_id: UUID) -> str:
        return job_channel(self._store.keys, job_id)

    async def publish(self, job_id: UUID, message: JobMessage) -> None:
        try:
            await self._client().publish(self.channel(job_id), message.to_json())
        except (RedisError, OSError):
            logger.warning("generation.job_publish_failed", job_id=str(job_id))

    @asynccontextmanager
    async def subscribe(self, job_id: UUID) -> AsyncGenerator[JobSubscription]:
        pubsub = self._client().pubsub()
        channel = self.channel(job_id)
        await pubsub.subscribe(channel)
        try:
            yield JobSubscription(pubsub)
        finally:
            with anyio.CancelScope(shield=True):
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.aclose()
                except (RedisError, OSError):
                    logger.warning("generation.job_unsubscribe_failed", job_id=str(job_id))
