import json
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, Protocol, Self, cast
from uuid import UUID

import anyio
import structlog
from redis.exceptions import RedisError

from motionile.core.redis import RedisKeyBuilder, RedisStore
from motionile.core.schemas import ResponseModel
from motionile.modules.media.domain import RenderStage, RenderStatus, is_terminal

CHANNEL_NAMESPACE = "render"
CANCEL_NAMESPACE = "render.cancel"
CANCEL_FLAG_TTL = timedelta(days=2)
CANCEL_FLAG_VALUE = b"1"

logger = structlog.get_logger(__name__)


def render_channel(keys: RedisKeyBuilder, render_id: UUID) -> str:
    return keys.key(CHANNEL_NAMESPACE, render_id)


def cancel_flag_key(keys: RedisKeyBuilder, render_id: UUID) -> str:
    return keys.key(CANCEL_NAMESPACE, render_id)


class RenderProgress(ResponseModel):
    render_id: UUID
    status: RenderStatus
    stage: RenderStage | None = None
    progress: int
    at: datetime
    error_code: str | None = None
    error_message: str | None = None

    @property
    def is_terminal(self) -> bool:
        return is_terminal(self.status)

    def to_json(self) -> str:
        payload: dict[str, Any] = self.model_dump(mode="json", by_alias=True)
        for name in ("errorCode", "errorMessage"):
            if payload[name] is None:
                del payload[name]
        return json.dumps(payload, separators=(",", ":"))

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


class RenderSubscription:
    def __init__(self, pubsub: PubSubLike) -> None:
        self._pubsub = pubsub

    async def next(self, timeout_seconds: float) -> RenderProgress | None:
        message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=timeout_seconds)
        if message is None:
            return None
        data = message.get("data")
        if not isinstance(data, bytes | str):
            return None
        return RenderProgress.from_json(data)


class RenderEvents:
    def __init__(self, store: RedisStore) -> None:
        self._store = store

    def _client(self) -> PublishingClient:
        return cast("PublishingClient", self._store.client)

    def channel(self, render_id: UUID) -> str:
        return render_channel(self._store.keys, render_id)

    async def publish(self, message: RenderProgress) -> None:
        try:
            await self._client().publish(self.channel(message.render_id), message.to_json())
        except (RedisError, OSError):
            logger.warning("media.render_publish_failed", render_id=str(message.render_id))

    async def flag_cancel(self, render_id: UUID) -> None:
        try:
            await self._store.set(cancel_flag_key(self._store.keys, render_id), CANCEL_FLAG_VALUE, ttl=CANCEL_FLAG_TTL)
        except (RedisError, OSError):
            logger.warning("media.render_cancel_flag_failed", render_id=str(render_id))

    async def cancel_flagged(self, render_id: UUID) -> bool:
        try:
            return await self._store.get(cancel_flag_key(self._store.keys, render_id)) is not None
        except (RedisError, OSError):
            return False

    @asynccontextmanager
    async def subscribe(self, render_id: UUID) -> AsyncGenerator[RenderSubscription]:
        pubsub = self._client().pubsub()
        channel = self.channel(render_id)
        await pubsub.subscribe(channel)
        try:
            yield RenderSubscription(pubsub)
        finally:
            with anyio.CancelScope(shield=True):
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.aclose()
                except (RedisError, OSError):
                    logger.warning("media.render_unsubscribe_failed", render_id=str(render_id))
