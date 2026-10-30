from collections.abc import Collection
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.pagination import Cursor, keyset_page
from motionile.engine.ai.job_options import AspectName, JobStatus
from motionile.modules.generation.models import Job, ShareLink, Storyboard
from motionile.modules.generation.repository import FRESH_ROWS, SqlJobRepository


@dataclass(frozen=True, slots=True)
class LibraryFilter:
    search: str | None = None
    aspect: AspectName | None = None


@dataclass(frozen=True, slots=True)
class LibraryRow:
    job: Job
    title: str | None
    share_slug: str | None


class LibraryStore(Protocol):
    async def page(
        self, user_id: UUID, library_filter: LibraryFilter, cursor: Cursor | None, limit: int
    ) -> list[LibraryRow]: ...

    async def fallback_scene_keys(self, job_ids: Collection[UUID]) -> dict[UUID, list[str]]: ...


class SqlLibraryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def page(
        self, user_id: UUID, library_filter: LibraryFilter, cursor: Cursor | None, limit: int
    ) -> list[LibraryRow]:
        title = (
            select(func.jsonb_extract_path_text(Storyboard.content, "title"))
            .where(Storyboard.job_id == Job.id, Storyboard.approved_at.is_not(None))
            .order_by(Storyboard.version.desc())
            .limit(1)
            .correlate(Job)
            .scalar_subquery()
        )
        slug = (
            select(ShareLink.slug)
            .where(ShareLink.job_id == Job.id, ShareLink.revoked_at.is_(None))
            .order_by(ShareLink.created_at.desc())
            .limit(1)
            .correlate(Job)
            .scalar_subquery()
        )
        statement = select(Job, title.label("title"), slug.label("share_slug")).where(
            and_(
                Job.user_id == user_id,
                Job.status == JobStatus.COMPLETED.value,
                Job.render_id.is_not(None),
            )
        )
        if library_filter.search is not None:
            statement = statement.where(
                or_(
                    Job.query.icontains(library_filter.search, autoescape=True),
                    title.icontains(library_filter.search, autoescape=True),
                )
            )
        if library_filter.aspect is not None:
            statement = statement.where(Job.options.contains({"aspects": [library_filter.aspect]}))
        paged = keyset_page(statement, created_at=Job.created_at, id_=Job.id, cursor=cursor, limit=limit)
        rows = (await self.session.execute(paged.execution_options(**FRESH_ROWS))).all()
        return [LibraryRow(job, found_title, found_slug) for job, found_title, found_slug in rows]

    async def fallback_scene_keys(self, job_ids: Collection[UUID]) -> dict[UUID, list[str]]:
        return await SqlJobRepository(self.session).fallback_scene_keys(job_ids)
