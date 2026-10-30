from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.pagination import Cursor
from motionile.engine.ai.job_options import JobOptions
from motionile.modules.generation.library_repository import (
    LibraryFilter,
    LibraryRow,
    LibraryStore,
    SqlLibraryRepository,
)
from motionile.modules.generation.library_schemas import LibraryItem
from motionile.modules.media import RenderNotFoundError, RenditionView

type LibraryStoreFactory = Callable[[AsyncSession], LibraryStore]


@dataclass(frozen=True, slots=True)
class LibraryResult:
    items: list[LibraryItem]
    next_cursor: Cursor | None


def thumbnail_of(options: JobOptions, renditions: list[RenditionView]) -> str | None:
    wanted = options.aspects[0]
    ordered = sorted(renditions, key=lambda item: item.aspect.value != wanted)
    return next((item.poster_url for item in ordered if item.poster_url is not None), None)


def duration_of(options: JobOptions, renditions: list[RenditionView]) -> int | None:
    known = [item.duration_ms for item in renditions if item.duration_ms is not None]
    return max(known) if known else options.target_duration_ms


class LibraryMedia(Protocol):
    async def renditions_for(self, session: AsyncSession, user_id: UUID, render_id: UUID) -> list[RenditionView]: ...


class LibraryService:
    def __init__(self, media: LibraryMedia, store_factory: LibraryStoreFactory = SqlLibraryRepository) -> None:
        self._media = media
        self._store_factory = store_factory

    async def page(
        self, session: AsyncSession, user_id: UUID, library_filter: LibraryFilter, cursor: Cursor | None, limit: int
    ) -> LibraryResult:
        store = self._store_factory(session)
        rows = await store.page(user_id, library_filter, cursor, limit)
        shown = rows[:limit]
        next_cursor = Cursor(shown[-1].job.created_at, shown[-1].job.id) if len(rows) > limit and shown else None
        fallbacks = await store.fallback_scene_keys([row.job.id for row in shown])
        items = [await self._item(session, user_id, row, fallbacks.get(row.job.id, [])) for row in shown]
        return LibraryResult(items, next_cursor)

    async def _item(self, session: AsyncSession, user_id: UUID, row: LibraryRow, fallbacks: list[str]) -> LibraryItem:
        job = row.job
        options = JobOptions.model_validate(job.options)
        renditions = await self._renditions(session, user_id, job.render_id)
        return LibraryItem(
            job_id=job.id,
            title=row.title or job.query,
            query=job.query,
            duration_ms=duration_of(options, renditions),
            aspects=options.aspects,
            thumbnail_url=thumbnail_of(options, renditions),
            fallback_scene_ids=fallbacks,
            renditions=renditions,
            share_slug=row.share_slug,
            created_at=job.created_at,
            completed_at=job.completed_at,
        )

    async def _renditions(self, session: AsyncSession, user_id: UUID, render_id: UUID | None) -> list[RenditionView]:
        if render_id is None:
            return []
        try:
            return await self._media.renditions_for(session, user_id, render_id)
        except RenderNotFoundError:
            return []
