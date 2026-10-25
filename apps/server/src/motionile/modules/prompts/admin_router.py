from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response, status

from motionile.core.dependencies import CursorCodecDep
from motionile.core.errors import problem_responses
from motionile.core.ratelimit.limiter import rate_limit
from motionile.core.schemas import PageQuery
from motionile.modules.auth import enforce_csrf
from motionile.modules.prompts.dependencies import EvalRunServiceDep, EvaluatorDep, ManagerDep, PromptsServiceDep
from motionile.modules.prompts.domain import MAX_VERSION_NUMBER, TEMPLATE_KEY_PATTERN
from motionile.modules.prompts.repository import RunFilter
from motionile.modules.prompts.schemas import (
    DiffQuery,
    DiffView,
    DraftRequest,
    EvalRunListQuery,
    EvalRunPage,
    EvalRunRequest,
    EvalRunView,
    TemplateList,
    VersionPage,
    VersionView,
)

NO_STORE = "no-store"
MAX_KEY_LENGTH = 64

TemplateKey = Annotated[str, Path(pattern=TEMPLATE_KEY_PATTERN, max_length=MAX_KEY_LENGTH)]
VersionPath = Annotated[int, Path(ge=1, le=MAX_VERSION_NUMBER)]

admin_prompts_router = APIRouter(
    prefix="/admin/prompts",
    tags=["admin-prompts"],
    dependencies=[Depends(enforce_csrf), Depends(rate_limit("api.default"))],
    responses=problem_responses(401, 403, 404, 422),
)
writes = [Depends(rate_limit("prompts.write"))]


@admin_prompts_router.get(
    "/templates",
    response_model=TemplateList,
    status_code=status.HTTP_200_OK,
    summary="List the prompt templates with their active version and latest evaluation status",
)
async def list_prompt_templates(_: ManagerDep, service: PromptsServiceDep) -> TemplateList:
    return TemplateList(items=await service.list_templates())


@admin_prompts_router.get(
    "/templates/{key}/versions",
    response_model=VersionPage,
    status_code=status.HTTP_200_OK,
    summary="List the versions of a prompt template without their text",
)
async def list_prompt_versions(
    key: TemplateKey,
    query: Annotated[PageQuery, Query()],
    _: ManagerDep,
    service: PromptsServiceDep,
    cursors: CursorCodecDep,
) -> VersionPage:
    cursor = cursors.decode(query.cursor) if query.cursor else None
    listing = await service.list_versions(key, cursor, query.limit)
    return VersionPage(
        items=listing.items,
        next_cursor=cursors.encode(listing.next_cursor) if listing.next_cursor is not None else None,
    )


@admin_prompts_router.get(
    "/templates/{key}/diff",
    response_model=DiffView,
    status_code=status.HTTP_200_OK,
    summary="Line diff of two versions with canary lines redacted; the only response that carries prompt text",
)
async def diff_prompt_versions(
    key: TemplateKey,
    query: Annotated[DiffQuery, Query()],
    actor: ManagerDep,
    service: PromptsServiceDep,
    response: Response,
) -> DiffView:
    response.headers["Cache-Control"] = NO_STORE
    return await service.diff(actor, key, query.from_version, query.to_version)


@admin_prompts_router.post(
    "/templates/{key}/versions",
    response_model=VersionView,
    status_code=status.HTTP_201_CREATED,
    summary="Create a draft version from a posted prompt text",
    dependencies=writes,
    responses=problem_responses(409),
)
async def create_prompt_draft(
    key: TemplateKey, body: DraftRequest, actor: ManagerDep, service: PromptsServiceDep
) -> VersionView:
    return await service.create_draft(actor, key, body)


@admin_prompts_router.post(
    "/templates/{key}/versions/{version}/activate",
    response_model=VersionView,
    status_code=status.HTTP_200_OK,
    summary="Activate a version once every required suite has a passing run that covers it",
    dependencies=writes,
    responses=problem_responses(409),
)
async def activate_prompt_version(
    key: TemplateKey, version: VersionPath, actor: ManagerDep, service: PromptsServiceDep
) -> VersionView:
    return await service.activate(actor, key, version)


@admin_prompts_router.post(
    "/templates/{key}/rollback",
    response_model=VersionView,
    status_code=status.HTTP_200_OK,
    summary="Activate the version that was active before the current one",
    dependencies=writes,
    responses=problem_responses(409),
)
async def rollback_prompt_template(key: TemplateKey, actor: ManagerDep, service: PromptsServiceDep) -> VersionView:
    return await service.rollback(actor, key)


@admin_prompts_router.post(
    "/eval-runs",
    response_model=EvalRunView,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start an evaluation run of a suite against prompt versions",
    dependencies=writes,
)
async def start_eval_run(body: EvalRunRequest, actor: EvaluatorDep, service: EvalRunServiceDep) -> EvalRunView:
    return await service.start_run(actor, body.suite, body.version_ids)


@admin_prompts_router.get(
    "/eval-runs",
    response_model=EvalRunPage,
    status_code=status.HTTP_200_OK,
    summary="List evaluation runs, newest first",
)
async def list_eval_runs(
    query: Annotated[EvalRunListQuery, Query()],
    _: ManagerDep,
    service: EvalRunServiceDep,
    cursors: CursorCodecDep,
) -> EvalRunPage:
    cursor = cursors.decode(query.cursor) if query.cursor else None
    listing = await service.page(
        RunFilter(query.suite, query.status.value if query.status else None), cursor, query.limit
    )
    return EvalRunPage(
        items=listing.items,
        next_cursor=cursors.encode(listing.next_cursor) if listing.next_cursor is not None else None,
    )


@admin_prompts_router.get(
    "/eval-runs/{run_id}",
    response_model=EvalRunView,
    status_code=status.HTTP_200_OK,
    summary="Read one evaluation run",
)
async def get_eval_run(run_id: UUID, _: ManagerDep, service: EvalRunServiceDep) -> EvalRunView:
    return await service.get(run_id)
