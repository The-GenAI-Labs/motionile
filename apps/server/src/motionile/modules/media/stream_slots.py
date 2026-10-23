from datetime import timedelta
from uuid import UUID, uuid4

import anyio
import structlog
from redis.exceptions import RedisError

from motionile.core.clock import Clock
from motionile.core.redis import RedisStore
from motionile.modules.media.exceptions import TooManyStreamsError

STREAMS_NAMESPACE = "render.streams"
MAX_STREAMS_PER_USER = 5
LEASE_SECONDS = 90.0
KEY_TTL = timedelta(hours=1)

logger = structlog.get_logger(__name__)


class StreamLease:
    def __init__(self, store: RedisStore, key: str, token: str, clock: Clock, lease_seconds: float) -> None:
        self._store = store
        self._key = key
        self._token = token
        self._clock = clock
        self._lease_seconds = lease_seconds

    def _expires_at(self) -> float:
        return self._clock.now().timestamp() + self._lease_seconds

    async def renew(self) -> None:
        try:
            await self._store.client.zadd(self._key, {self._token: self._expires_at()}, xx=True)
        except (RedisError, OSError):
            logger.warning("media.render_stream_renew_failed")

    async def release(self) -> None:
        with anyio.CancelScope(shield=True):
            try:
                await self._store.client.zrem(self._key, self._token)
            except (RedisError, OSError):
                logger.warning("media.render_stream_release_failed")


class StreamSlots:
    def __init__(
        self,
        store: RedisStore,
        clock: Clock,
        *,
        limit: int = MAX_STREAMS_PER_USER,
        lease_seconds: float = LEASE_SECONDS,
    ) -> None:
        self._store = store
        self._clock = clock
        self._limit = limit
        self._lease_seconds = lease_seconds

    async def acquire(self, user_id: UUID) -> StreamLease:
        key = self._store.keys.key(STREAMS_NAMESPACE, user_id)
        token = uuid4().hex
        now = self._clock.now().timestamp()
        lease = StreamLease(self._store, key, token, self._clock, self._lease_seconds)
        async with self._store.client.pipeline(transaction=True) as pipeline:
            pipeline.zremrangebyscore(key, 0, now)
            pipeline.zadd(key, {token: now + self._lease_seconds})
            pipeline.zcard(key)
            pipeline.expire(key, int(KEY_TTL.total_seconds()))
            results = await pipeline.execute()
        if int(results[2]) > self._limit:
            await lease.release()
            raise TooManyStreamsError
        return lease
