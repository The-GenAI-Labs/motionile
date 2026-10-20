from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

type UserExporter = Callable[[AsyncSession, UUID], Awaitable[object]]


class ExportRegistry:
    def __init__(self) -> None:
        self._exporters: dict[str, UserExporter] = {}

    def register(self, name: str, exporter: UserExporter) -> None:
        if name in self._exporters:
            raise ValueError(f"exporter {name!r} already exists")
        self._exporters[name] = exporter

    async def export(self, session: AsyncSession, user_id: UUID) -> dict[str, object]:
        return {name: await exporter(session, user_id) for name, exporter in self._exporters.items()}


registry = ExportRegistry()
