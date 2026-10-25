import time
import weakref
from collections.abc import Callable
from typing import Final

from motionile.engine.ai.ports import ActivePrompt
from motionile.modules.prompts.exceptions import PromptNotActiveError
from motionile.modules.prompts.repository import SqlPromptRepository, StoreFactory, Transaction

CACHE_TTL_SECONDS: Final = 30.0

type Monotonic = Callable[[], float]


class DatabasePromptStore:
    def __init__(
        self,
        transaction: Transaction,
        *,
        store_factory: StoreFactory = SqlPromptRepository,
        ttl_seconds: float = CACHE_TTL_SECONDS,
        monotonic: Monotonic = time.monotonic,
    ) -> None:
        self._transaction = transaction
        self._store_factory = store_factory
        self._ttl_seconds = ttl_seconds
        self._monotonic = monotonic
        self._entries: dict[str, tuple[float, ActivePrompt]] = {}
        self._everything: tuple[float, list[ActivePrompt]] | None = None
        _stores.add(self)

    async def active(self, key: str) -> ActivePrompt:
        cached = self._entries.get(key)
        if cached is not None and cached[0] > self._monotonic():
            return cached[1]
        async with self._transaction() as session:
            prompt = await self._store_factory(session).active_prompt(key)
        if prompt is None:
            raise PromptNotActiveError(key)
        self._entries[key] = (self._monotonic() + self._ttl_seconds, prompt)
        return prompt

    async def all_active(self) -> list[ActivePrompt]:
        if self._everything is not None and self._everything[0] > self._monotonic():
            return list(self._everything[1])
        async with self._transaction() as session:
            prompts = await self._store_factory(session).active_prompts()
        expires_at = self._monotonic() + self._ttl_seconds
        self._entries = {prompt.key: (expires_at, prompt) for prompt in prompts}
        self._everything = (expires_at, prompts)
        return list(prompts)

    def invalidate(self) -> None:
        self._entries.clear()
        self._everything = None


_stores: weakref.WeakSet[DatabasePromptStore] = weakref.WeakSet()


def invalidate_active_prompts() -> None:
    for store in list(_stores):
        store.invalidate()


async def invalidate_active_prompts_after_commit() -> None:
    invalidate_active_prompts()
