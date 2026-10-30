from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import StringConstraints

from motionile.core.schemas import CursorPage, PageQuery, ResponseModel
from motionile.engine.ai.job_options import AspectName
from motionile.modules.media import RenditionView

MAX_SEARCH_CHARS = 100

type SearchText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_SEARCH_CHARS)]


class LibraryQuery(PageQuery):
    q: SearchText | None = None
    aspect: AspectName | None = None


class LibraryItem(ResponseModel):
    job_id: UUID
    title: str
    query: str
    duration_ms: int | None
    aspects: list[AspectName]
    thumbnail_url: str | None
    fallback_scene_ids: list[str]
    renditions: list[RenditionView]
    share_slug: str | None
    created_at: datetime
    completed_at: datetime | None


class LibraryPage(CursorPage[LibraryItem]):
    pass
