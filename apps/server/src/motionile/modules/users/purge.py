from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.resources import Resources

type PurgeHook = Callable[[Resources, AsyncSession, UUID], Awaitable[None]]


class PurgeRegistry:
    def __init__(self) -> None:
        self._hooks: dict[str, PurgeHook] = {}

    def register(self, name: str, hook: PurgeHook) -> None:
        if name in self._hooks:
            raise ValueError(f"purge hook {name!r} already exists")
        self._hooks[name] = hook

    def names(self) -> tuple[str, ...]:
        return tuple(self._hooks)

    async def run(self, resources: Resources, session: AsyncSession, user_id: UUID) -> None:
        for hook in self._hooks.values():
            await hook(resources, session, user_id)


purge_registry = PurgeRegistry()
