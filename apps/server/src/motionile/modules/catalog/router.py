from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.dependencies import CursorCodecDep, DatabaseDep, RedisStoreDep
from motionile.core.errors import problem_responses
from motionile.core.ratelimit.limiter import rate_limit
from motionile.core.schemas import PageQuery
from motionile.modules.access import CatalogManageDep
from motionile.modules.audit import ActorType, AuditEvent, context_from_request, record
from motionile.modules.auth import enforce_csrf
from motionile.modules.catalog.schemas import (
    AdminCatalogTreeResponse,
    CatalogCategoryResponse,
    CatalogPathsResponse,
    CatalogRedirectResponse,
    CatalogReorderRequest,
    CatalogTopicResponse,
    CatalogTreeResponse,
    CategoryDetailResponse,
    CategoryUpdateRequest,
    CategoryWriteRequest,
    SubcategoryDetailResponse,
    TopicDetailResponse,
    TopicSearchQuery,
    TopicSearchResponse,
    TopicUpdateRequest,
    TopicWriteRequest,
)
from motionile.modules.catalog.service import CatalogService

catalog_router = APIRouter(
    prefix="/catalog",
    tags=["catalog"],
    dependencies=[Depends(enforce_csrf), Depends(rate_limit("api.default"))],
    responses=problem_responses(404, 422),
)
catalog_admin_router = APIRouter(
    prefix="/admin/catalog",
    tags=["admin-catalog"],
    dependencies=[Depends(enforce_csrf), Depends(rate_limit("api.default"))],
    responses=problem_responses(401, 403, 404, 409, 422),
)


def service(
    database: DatabaseDep, redis: RedisStoreDep, cursor: CursorCodecDep
) -> tuple[DatabaseDep, RedisStoreDep, CursorCodecDep]:
    return database, redis, cursor


CatalogResourcesDep = Annotated[
    tuple[DatabaseDep, RedisStoreDep, CursorCodecDep],
    Depends(service),
]


@catalog_router.get("/tree", response_model=CatalogTreeResponse, status_code=200, summary="Get the active catalog tree")
async def catalog_tree(resources: CatalogResourcesDep) -> CatalogTreeResponse:
    database, redis, cursor = resources
    async with database.transaction() as session:
        return await CatalogService(session, redis, cursor).tree()


@catalog_router.get(
    "/categories/{category}", response_model=CategoryDetailResponse, status_code=200, summary="Get a catalog category"
)
async def catalog_category(category: str, resources: CatalogResourcesDep) -> CategoryDetailResponse:
    database, redis, cursor = resources
    async with database.transaction() as session:
        return await CatalogService(session, redis, cursor).category_detail(category)


@catalog_router.get(
    "/categories/{category}/{subcategory}",
    response_model=SubcategoryDetailResponse,
    status_code=200,
    summary="Get a catalog subcategory",
)
async def catalog_subcategory(
    category: str,
    subcategory: str,
    query: Annotated[PageQuery, Query()],
    resources: CatalogResourcesDep,
) -> SubcategoryDetailResponse:
    database, redis, cursor = resources
    async with database.transaction() as session:
        return await CatalogService(session, redis, cursor).subcategory_detail(
            category, subcategory, query.cursor, query.limit
        )


@catalog_router.get(
    "/topics/{category}/{subcategory}/{topic}",
    response_model=TopicDetailResponse,
    status_code=200,
    summary="Get a catalog topic",
)
async def catalog_topic(
    category: str, subcategory: str, topic: str, resources: CatalogResourcesDep
) -> TopicDetailResponse:
    database, redis, cursor = resources
    async with database.transaction() as session:
        return await CatalogService(session, redis, cursor).topic_detail(category, subcategory, topic)


@catalog_router.get("/search", response_model=TopicSearchResponse, status_code=200, summary="Search catalog topics")
async def catalog_search(
    query: Annotated[TopicSearchQuery, Query()], resources: CatalogResourcesDep
) -> TopicSearchResponse:
    database, redis, cursor = resources
    async with database.transaction() as session:
        return TopicSearchResponse(
            items=await CatalogService(session, redis, cursor).search(query.q, query.limit), next_cursor=None
        )


@catalog_router.get(
    "/redirects", response_model=CatalogRedirectResponse, status_code=200, summary="Resolve a historical catalog path"
)
async def catalog_redirect(
    path: Annotated[str, Query(min_length=9, max_length=400, pattern=r"^/explore/")],
    resources: CatalogResourcesDep,
) -> CatalogRedirectResponse:
    database, redis, cursor = resources
    async with database.transaction() as session:
        return await CatalogService(session, redis, cursor).redirect(path)


@catalog_router.get("/paths", response_model=CatalogPathsResponse, status_code=200, summary="List active catalog paths")
async def catalog_paths(resources: CatalogResourcesDep) -> CatalogPathsResponse:
    database, redis, cursor = resources
    async with database.transaction() as session:
        return await CatalogService(session, redis, cursor).paths()


async def audit_catalog(
    session: AsyncSession,
    request: Request,
    principal: CatalogManageDep,
    event: AuditEvent,
) -> None:
    event.actor_user_id = principal.user_id
    await record(
        session,
        event,
        context_from_request(request),
    )


@catalog_admin_router.get(
    "/tree", response_model=AdminCatalogTreeResponse, status_code=200, summary="List the catalog for administration"
)
async def admin_catalog_tree(
    request: Request, resources: CatalogResourcesDep, principal: CatalogManageDep
) -> AdminCatalogTreeResponse:
    database, redis, cursor = resources
    async with database.transaction() as session:
        result = await CatalogService(session, redis, cursor).admin_tree()
        await audit_catalog(
            session,
            request,
            principal,
            AuditEvent(action="catalog.listed", actor_type=ActorType.ADMIN, target_type="catalog"),
        )
        return result


@catalog_admin_router.post(
    "/categories", response_model=CatalogCategoryResponse, status_code=201, summary="Create a category or subcategory"
)
async def create_category(
    body: CategoryWriteRequest,
    request: Request,
    resources: CatalogResourcesDep,
    principal: CatalogManageDep,
) -> CatalogCategoryResponse:
    database, redis, cursor = resources
    async with database.transaction() as session:
        result = await CatalogService(session, redis, cursor).create_category(body)
        await audit_catalog(
            session,
            request,
            principal,
            AuditEvent(
                action="catalog.category.created",
                actor_type=ActorType.ADMIN,
                target_type=body.level,
                target_id=str(result.id),
            ),
        )
        return result


@catalog_admin_router.put(
    "/categories/{category_id}",
    response_model=CatalogCategoryResponse,
    status_code=200,
    summary="Update a category or subcategory",
)
async def update_category(
    category_id: UUID,
    body: CategoryUpdateRequest,
    request: Request,
    resources: CatalogResourcesDep,
    principal: CatalogManageDep,
) -> CatalogCategoryResponse:
    database, redis, cursor = resources
    async with database.transaction() as session:
        result = await CatalogService(session, redis, cursor).update_category(category_id, body)
        await audit_catalog(
            session,
            request,
            principal,
            AuditEvent(
                action="catalog.category.updated",
                actor_type=ActorType.ADMIN,
                target_type=body.level,
                target_id=str(category_id),
            ),
        )
        return result


@catalog_admin_router.post(
    "/topics", response_model=CatalogTopicResponse, status_code=201, summary="Create a catalog topic"
)
async def create_topic(
    body: TopicWriteRequest,
    request: Request,
    resources: CatalogResourcesDep,
    principal: CatalogManageDep,
) -> CatalogTopicResponse:
    database, redis, cursor = resources
    async with database.transaction() as session:
        result = await CatalogService(session, redis, cursor).create_topic(body)
        await audit_catalog(
            session,
            request,
            principal,
            AuditEvent(
                action="catalog.topic.created",
                actor_type=ActorType.ADMIN,
                target_type="topic",
                target_id=str(result.id),
            ),
        )
        return result


@catalog_admin_router.put(
    "/topics/{topic_id}", response_model=CatalogTopicResponse, status_code=200, summary="Update a catalog topic"
)
async def update_topic(
    topic_id: UUID,
    body: TopicUpdateRequest,
    request: Request,
    resources: CatalogResourcesDep,
    principal: CatalogManageDep,
) -> CatalogTopicResponse:
    database, redis, cursor = resources
    async with database.transaction() as session:
        result = await CatalogService(session, redis, cursor).update_topic(topic_id, body)
        await audit_catalog(
            session,
            request,
            principal,
            AuditEvent(
                action="catalog.topic.updated",
                actor_type=ActorType.ADMIN,
                target_type="topic",
                target_id=str(topic_id),
            ),
        )
        return result


@catalog_admin_router.put("/reorder", response_model=None, status_code=204, summary="Reorder catalog entities")
async def reorder_catalog(
    body: CatalogReorderRequest,
    request: Request,
    resources: CatalogResourcesDep,
    principal: CatalogManageDep,
) -> None:
    database, redis, cursor = resources
    async with database.transaction() as session:
        await CatalogService(session, redis, cursor).reorder(body)
        await audit_catalog(
            session,
            request,
            principal,
            AuditEvent(action="catalog.reordered", actor_type=ActorType.ADMIN, target_type=body.entity_type),
        )
