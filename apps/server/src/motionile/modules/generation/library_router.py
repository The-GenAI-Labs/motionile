from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from motionile.core.dependencies import CursorCodecDep, DatabaseDep
from motionile.core.errors import problem_responses
from motionile.core.ratelimit.limiter import rate_limit
from motionile.modules.auth import enforce_csrf
from motionile.modules.generation.dependencies import CurrentUserIdDep, LibraryServiceDep
from motionile.modules.generation.library_repository import LibraryFilter
from motionile.modules.generation.library_schemas import LibraryPage, LibraryQuery

library_router = APIRouter(
    prefix="/library",
    tags=["library"],
    dependencies=[Depends(enforce_csrf), Depends(rate_limit("api.default"))],
    responses=problem_responses(status.HTTP_401_UNAUTHORIZED),
)


@library_router.get(
    "",
    response_model=LibraryPage,
    status_code=status.HTTP_200_OK,
    summary="List your finished videos with thumbnails, durations and playable renditions",
    responses=problem_responses(status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def list_library(
    query: Annotated[LibraryQuery, Query()],
    user_id: CurrentUserIdDep,
    database: DatabaseDep,
    cursors: CursorCodecDep,
    service: LibraryServiceDep,
) -> LibraryPage:
    cursor = cursors.decode(query.cursor) if query.cursor else None
    async with database.transaction() as session:
        result = await service.page(session, user_id, LibraryFilter(query.q, query.aspect), cursor, query.limit)
    return LibraryPage(
        items=result.items,
        next_cursor=cursors.encode(result.next_cursor) if result.next_cursor is not None else None,
    )
