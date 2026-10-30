from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

from motionile.core.dependencies import CursorCodecDep
from motionile.core.errors import problem_responses
from motionile.core.ratelimit.limiter import rate_limit
from motionile.engine.ai.job_options import SLUG_PATTERN
from motionile.modules.access import SkillsManageDep
from motionile.modules.auth import enforce_csrf
from motionile.modules.skills.dependencies import SkillsAdminDep, SkillsServiceDep
from motionile.modules.skills.schemas import ReseedView, SkillDetailView, SkillListQuery, SkillPage

MAX_SLUG_LENGTH = 64

SkillSlug = Annotated[str, Path(pattern=SLUG_PATTERN, max_length=MAX_SLUG_LENGTH)]

admin_skills_router = APIRouter(
    prefix="/admin/skills",
    tags=["admin-skills"],
    dependencies=[Depends(enforce_csrf), Depends(rate_limit("api.default"))],
    responses=problem_responses(401, 403, 404, 422),
)


@admin_skills_router.get(
    "",
    response_model=SkillPage,
    status_code=status.HTTP_200_OK,
    summary="List the system skills with their version and embedding status, never their text",
)
async def list_system_skills(
    query: Annotated[SkillListQuery, Query()],
    _: SkillsManageDep,
    service: SkillsServiceDep,
    cursors: CursorCodecDep,
) -> SkillPage:
    cursor = cursors.decode(query.cursor) if query.cursor else None
    listing = await service.list_skills(query.layer, cursor, query.limit)
    return SkillPage(
        items=listing.items,
        next_cursor=cursors.encode(listing.next_cursor) if listing.next_cursor is not None else None,
    )


@admin_skills_router.post(
    "/reseed",
    response_model=ReseedView,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Synchronize the system skills with the shipped library; unchanged skills are left alone",
    responses=problem_responses(500, 502),
    dependencies=[Depends(rate_limit("skills.write"))],
)
async def reseed_system_skills(admin: SkillsAdminDep, service: SkillsServiceDep) -> ReseedView:
    return await service.reseed(admin.user_id, admin.context)


@admin_skills_router.get(
    "/{slug}",
    response_model=SkillDetailView,
    status_code=status.HTTP_200_OK,
    summary="Read a system skill with its version history, never its text",
)
async def get_system_skill(slug: SkillSlug, _: SkillsManageDep, service: SkillsServiceDep) -> SkillDetailView:
    return await service.get_skill(slug)
