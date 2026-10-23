from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import timedelta
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.redis import RedisKeyBuilder

type Transaction = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class KeyValueStore(Protocol):
    keys: RedisKeyBuilder

    async def set(self, key: str, value: bytes | str, *, ttl: timedelta) -> None: ...

    async def set_if_absent(self, key: str, value: bytes | str, *, ttl: timedelta) -> bool: ...

    async def get(self, key: str) -> bytes | None: ...

    async def delete(self, key: str) -> None: ...
