from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.ids import new_id
from motionile.modules.generation.models import Job, ShareLink, Storyboard
from motionile.modules.generation.repository import FRESH_ROWS, SqlJobRepository, violates

SLUG_CONSTRAINT = "uq_share_links_slug"


class ShareStore(Protocol):
    async def owned_job(self, user_id: UUID, job_id: UUID) -> Job | None: ...

    async def revoke(self, job_id: UUID, rendition_id: UUID | None, at: datetime) -> int: ...

    async def insert(
        self, job_id: UUID, rendition_id: UUID, slug: str, *, allow_indexing: bool
    ) -> ShareLink | None: ...

    async def find(self, slug: str) -> tuple[ShareLink, Job] | None: ...

    async def record_view(self, link_id: UUID) -> None: ...

    async def approved_content(self, job_id: UUID) -> dict[str, Any] | None: ...


class SqlShareRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def owned_job(self, user_id: UUID, job_id: UUID) -> Job | None:
        return await SqlJobRepository(self.session).get_owned(user_id, job_id, lock=True)

    async def revoke(self, job_id: UUID, rendition_id: UUID | None, at: datetime) -> int:
        statement = (
            update(ShareLink)
            .where(ShareLink.job_id == job_id, ShareLink.revoked_at.is_(None))
            .values(revoked_at=at, updated_at=func.now())
            .returning(ShareLink.id)
        )
        if rendition_id is not None:
            statement = statement.where(ShareLink.rendition_id == rendition_id)
        return len(list(await self.session.scalars(statement)))

    async def insert(self, job_id: UUID, rendition_id: UUID, slug: str, *, allow_indexing: bool) -> ShareLink | None:
        link = ShareLink(id=new_id(), job_id=job_id, slug=slug, rendition_id=rendition_id, is_public=allow_indexing)
        try:
            async with self.session.begin_nested():
                self.session.add(link)
                await self.session.flush()
        except IntegrityError as error:
            if violates(error, SLUG_CONSTRAINT):
                return None
            raise
        await self.session.refresh(link)
        return link

    async def find(self, slug: str) -> tuple[ShareLink, Job] | None:
        statement = (
            select(ShareLink, Job)
            .join(Job, Job.id == ShareLink.job_id)
            .where(ShareLink.slug == slug)
            .execution_options(**FRESH_ROWS)
        )
        found = (await self.session.execute(statement)).first()
        return (found[0], found[1]) if found is not None else None

    async def record_view(self, link_id: UUID) -> None:
        await self.session.execute(
            update(ShareLink).where(ShareLink.id == link_id).values(view_count=ShareLink.view_count + 1)
        )

    async def approved_content(self, job_id: UUID) -> dict[str, Any] | None:
        statement = (
            select(Storyboard.content)
            .where(Storyboard.job_id == job_id, Storyboard.approved_at.is_not(None))
            .order_by(Storyboard.version.desc())
            .limit(1)
        )
        return await self.session.scalar(statement)
