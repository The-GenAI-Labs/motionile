from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.redis import RedisStore
from motionile.modules.platform import PlatformService

MAX_CLONED_KEY = "voices.max_cloned_per_user"
CLONE_COST_KEY = "voices.clone_credit_cost"
STATEMENT_KEY = "voices.consent_statement"
STATEMENT_VERSION_KEY = "voices.consent_statement_version"


class RuntimeSettings(Protocol):
    async def max_cloned_per_user(self, session: AsyncSession) -> int: ...

    async def clone_credit_cost(self, session: AsyncSession) -> int: ...

    async def consent_statement(self, session: AsyncSession) -> str: ...

    async def consent_statement_version(self, session: AsyncSession) -> str: ...


class PlatformRuntimeSettings:
    def __init__(self, redis: RedisStore) -> None:
        self._redis = redis

    async def max_cloned_per_user(self, session: AsyncSession) -> int:
        return await self._integer(session, MAX_CLONED_KEY)

    async def clone_credit_cost(self, session: AsyncSession) -> int:
        return await self._integer(session, CLONE_COST_KEY)

    async def consent_statement(self, session: AsyncSession) -> str:
        return await self._text(session, STATEMENT_KEY)

    async def consent_statement_version(self, session: AsyncSession) -> str:
        return await self._text(session, STATEMENT_VERSION_KEY)

    async def _integer(self, session: AsyncSession, key: str) -> int:
        value = await PlatformService(session, self._redis).setting_value(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"setting {key} is not an integer")
        return value

    async def _text(self, session: AsyncSession, key: str) -> str:
        value = await PlatformService(session, self._redis).setting_value(key)
        if not isinstance(value, str):
            raise TypeError(f"setting {key} is not text")
        return value
