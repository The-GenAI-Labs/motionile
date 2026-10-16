import json
from datetime import timedelta
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.db import after_commit
from motionile.core.errors import ConflictError, NotFoundError, ValidationAppError
from motionile.core.ids import new_id
from motionile.core.pagination import Cursor, CursorCodec, build_page
from motionile.core.redis import RedisStore
from motionile.core.schemas import CursorPage
from motionile.modules.catalog.models import CatalogSlugHistory, Category, Topic
from motionile.modules.catalog.repository import CatalogRepository
from motionile.modules.catalog.schemas import (
    AdminCatalogTreeResponse,
    CatalogCategoryResponse,
    CatalogPathResponse,
    CatalogPathsResponse,
    CatalogRedirectResponse,
    CatalogReorderRequest,
    CatalogTopicResponse,
    CatalogTreeResponse,
    CategoryDetailResponse,
    CategoryTreeItem,
    CategoryUpdateRequest,
    CategoryWriteRequest,
    SubcategoryDetailResponse,
    TopicDetailResponse,
    TopicSearchResult,
    TopicUpdateRequest,
    TopicWriteRequest,
)
from motionile.modules.catalog.tasks import defer_revalidation

CACHE_TTL = timedelta(minutes=15)
CACHE_GENERATION_TTL = timedelta(days=3650)


class CatalogService:
    def __init__(self, session: AsyncSession, redis: RedisStore, cursor_codec: CursorCodec) -> None:
        self.session = session
        self.redis = redis
        self.cursor_codec = cursor_codec
        self.repository = CatalogRepository(session)

    async def tree(self, *, active_only: bool = True) -> CatalogTreeResponse:
        cached = await self._cache_get("tree", CatalogTreeResponse) if active_only else None
        if cached is not None:
            return cached
        categories = await self.repository.categories(active_only=active_only)
        children: dict[UUID, list[CatalogCategoryResponse]] = {}
        for category in categories:
            if category.parent_id is not None:
                children.setdefault(category.parent_id, []).append(self._category(category))
        result = CatalogTreeResponse(
            categories=[
                CategoryTreeItem(**self._category(category).model_dump(), children=children.get(category.id, []))
                for category in categories
                if category.parent_id is None
            ]
        )
        if active_only:
            await self._cache_set("tree", result)
        return result

    async def admin_tree(self) -> AdminCatalogTreeResponse:
        tree = await self.tree(active_only=False)
        return AdminCatalogTreeResponse(
            categories=tree.categories,
            topics=[self._topic(topic) for topic in await self.repository.all_topics()],
        )

    async def category_detail(self, slug: str) -> CategoryDetailResponse:
        cached = await self._cache_get(f"category:{slug}", CategoryDetailResponse)
        if cached is not None:
            return cached
        category = await self._top(slug)
        rows = await self.repository.categories()
        result = CategoryDetailResponse(
            category=self._category(category),
            subcategories=[self._category(item) for item in rows if item.parent_id == category.id],
        )
        await self._cache_set(f"category:{slug}", result)
        return result

    async def subcategory_detail(
        self, category_slug: str, subcategory_slug: str, cursor_token: str | None, limit: int
    ) -> SubcategoryDetailResponse:
        cache_part = f"subcategory:{category_slug}:{subcategory_slug}:{cursor_token or '-'}:{limit}"
        cached = await self._cache_get(cache_part, SubcategoryDetailResponse)
        if cached is not None:
            return cached
        category = await self._top(category_slug)
        subcategory = await self.repository.subcategory_by_slug(category.id, subcategory_slug)
        if subcategory is None:
            raise NotFoundError(code="catalog_path_not_found")
        cursor = self.cursor_codec.decode(cursor_token) if cursor_token else None
        rows = await self.repository.topics(subcategory.id, cursor, limit)
        items, next_cursor = build_page(
            rows,
            limit=limit,
            codec=self.cursor_codec,
            key=lambda topic: Cursor(topic.created_at, topic.id),
        )
        result = SubcategoryDetailResponse(
            category=self._category(category),
            subcategory=self._category(subcategory),
            topics=CursorPage(items=[self._topic(item) for item in items], next_cursor=next_cursor),
        )
        await self._cache_set(cache_part, result)
        return result

    async def topic_detail(self, category_slug: str, subcategory_slug: str, topic_slug: str) -> TopicDetailResponse:
        cache_part = f"topic:{category_slug}:{subcategory_slug}:{topic_slug}"
        cached = await self._cache_get(cache_part, TopicDetailResponse)
        if cached is not None:
            return cached
        category = await self._top(category_slug)
        subcategory = await self.repository.subcategory_by_slug(category.id, subcategory_slug)
        if subcategory is None:
            raise NotFoundError(code="catalog_path_not_found")
        topic = await self.repository.topic_by_slug(subcategory.id, topic_slug)
        if topic is None:
            raise NotFoundError(code="catalog_path_not_found")
        result = TopicDetailResponse(
            category=self._category(category),
            subcategory=self._category(subcategory),
            topic=self._topic(topic),
            related_topics=[self._topic(item) for item in await self.repository.related(topic)],
        )
        await self._cache_set(cache_part, result)
        return result

    async def search(self, query: str, limit: int) -> list[TopicSearchResult]:
        cache_part = f"search:{query.casefold()}:{limit}"
        cached = await self._cache_get(cache_part, list[TopicSearchResult])
        if cached is not None:
            return cached
        result = [
            TopicSearchResult(**self._topic(item).model_dump(), path=await self._topic_path(item))
            for item in await self.repository.search(query, limit)
        ]
        await self._cache_set(cache_part, result)
        return result

    async def redirect(self, path: str) -> CatalogRedirectResponse:
        cached = await self._cache_get(f"redirect:{path}", CatalogRedirectResponse)
        if cached is not None:
            return cached
        history = await self.repository.redirect(path)
        if history is None:
            raise NotFoundError(code="catalog_redirect_not_found")
        destination = await self._current_path(history.entity_type, history.entity_id)
        result = CatalogRedirectResponse(destination=destination)
        await self._cache_set(f"redirect:{path}", result)
        return result

    async def paths(self) -> CatalogPathsResponse:
        cached = await self._cache_get("paths", CatalogPathsResponse)
        if cached is not None:
            return cached
        result: list[CatalogPathResponse] = []
        for category, subcategory, topic in await self.repository.paths():
            path = f"/explore/{category.slug}"
            modified = category.updated_at
            if subcategory is not None:
                path += f"/{subcategory.slug}"
                modified = max(modified, subcategory.updated_at)
            if topic is not None:
                path += f"/{topic.slug}"
                modified = max(modified, topic.updated_at)
            result.append(CatalogPathResponse(path=path, last_modified=modified))
        response = CatalogPathsResponse(items=result)
        await self._cache_set("paths", response)
        return response

    async def create_category(self, body: CategoryWriteRequest) -> CatalogCategoryResponse:
        await self._validate_category_parent(body)
        category = Category(id=new_id(), **body.model_dump())
        try:
            await self.repository.create_category(category)
        except IntegrityError as error:
            raise ConflictError(code="catalog_slug_exists") from error
        self._changed({"catalog", f"catalog:{category.slug}"})
        return self._category(category)

    async def update_category(self, category_id: UUID, body: CategoryUpdateRequest) -> CatalogCategoryResponse:
        category = await self.repository.category(category_id, lock=True)
        if category is None:
            raise NotFoundError(code="catalog_entity_not_found")
        if category.version != body.version:
            raise ConflictError(code="catalog_version_conflict")
        await self._validate_category_parent(body, category_id)
        if category.slug != body.slug:
            await self._record_category_history(category)
        for key, value in body.model_dump(exclude={"version"}).items():
            setattr(category, key, value)
        category.version += 1
        try:
            await self.session.flush()
        except IntegrityError as error:
            raise ConflictError(code="catalog_slug_exists") from error
        self._changed({"catalog", f"catalog:{category.id}"})
        return self._category(category)

    async def create_topic(self, body: TopicWriteRequest) -> CatalogTopicResponse:
        await self._validate_topic_parent(body.category_id)
        topic = Topic(id=new_id(), **body.model_dump())
        try:
            await self.repository.create_topic(topic)
        except IntegrityError as error:
            raise ConflictError(code="catalog_slug_exists") from error
        self._changed({"catalog", f"catalog:{topic.id}"})
        return self._topic(topic)

    async def update_topic(self, topic_id: UUID, body: TopicUpdateRequest) -> CatalogTopicResponse:
        topic = await self.repository.topic(topic_id, lock=True)
        if topic is None:
            raise NotFoundError(code="catalog_entity_not_found")
        if topic.version != body.version:
            raise ConflictError(code="catalog_version_conflict")
        await self._validate_topic_parent(body.category_id)
        if topic.slug != body.slug or topic.category_id != body.category_id:
            await self.repository.add_history(
                CatalogSlugHistory(
                    id=new_id(), entity_type="topic", entity_id=topic.id, old_path=await self._topic_path(topic)
                )
            )
        for key, value in body.model_dump(exclude={"version"}).items():
            setattr(topic, key, value)
        topic.version += 1
        try:
            await self.session.flush()
        except IntegrityError as error:
            raise ConflictError(code="catalog_slug_exists") from error
        self._changed({"catalog", f"catalog:{topic.id}"})
        return self._topic(topic)

    async def reorder(self, body: CatalogReorderRequest) -> None:
        positions = {item.id: (item.sort_order, item.version) for item in body.items}
        changed = (
            await self.repository.reorder_categories(positions)
            if body.entity_type == "category"
            else await self.repository.reorder_topics(positions)
        )
        if changed != len(positions):
            raise ConflictError(code="catalog_version_conflict")
        self._changed({"catalog"})

    async def _top(self, slug: str) -> Category:
        category = await self.repository.top_by_slug(slug)
        if category is None:
            raise NotFoundError(code="catalog_path_not_found")
        return category

    async def _validate_category_parent(self, body: CategoryWriteRequest, entity_id: UUID | None = None) -> None:
        if body.parent_id is None:
            return
        if body.parent_id == entity_id:
            raise ValidationAppError(code="catalog_depth_invalid")
        parent = await self.repository.category(body.parent_id)
        if parent is None or parent.level != "category":
            raise ValidationAppError(code="catalog_depth_invalid")

    async def _validate_topic_parent(self, category_id: UUID) -> None:
        parent = await self.repository.category(category_id)
        if parent is None or parent.level != "subcategory":
            raise ValidationAppError(code="catalog_depth_invalid")

    async def _category_path(self, category: Category) -> str:
        if category.parent_id is None:
            return f"/explore/{category.slug}"
        parent = await self.repository.category(category.parent_id)
        if parent is None:
            raise ValidationAppError(code="catalog_depth_invalid")
        return f"/explore/{parent.slug}/{category.slug}"

    async def _topic_path(self, topic: Topic) -> str:
        subcategory = await self.repository.category(topic.category_id)
        if subcategory is None:
            raise ValidationAppError(code="catalog_depth_invalid")
        return f"{await self._category_path(subcategory)}/{topic.slug}"

    async def _current_path(self, entity_type: str, entity_id: UUID) -> str:
        if entity_type == "topic":
            topic = await self.repository.topic(entity_id)
            if topic is None or not topic.is_active or not await self._ancestors_active(topic.category_id):
                raise NotFoundError(code="catalog_redirect_not_found")
            return await self._topic_path(topic)
        category = await self.repository.category(entity_id)
        if category is None or not category.is_active:
            raise NotFoundError(code="catalog_redirect_not_found")
        if category.parent_id is not None:
            parent = await self.repository.category(category.parent_id)
            if parent is None or not parent.is_active:
                raise NotFoundError(code="catalog_redirect_not_found")
        return await self._category_path(category)

    async def _ancestors_active(self, subcategory_id: UUID) -> bool:
        subcategory = await self.repository.category(subcategory_id)
        if subcategory is None or not subcategory.is_active or subcategory.parent_id is None:
            return False
        parent = await self.repository.category(subcategory.parent_id)
        return parent is not None and parent.is_active

    async def _record_history(self, entity_type: str, entity_id: UUID, old_path: str) -> None:
        existing = await self.repository.redirect(old_path)
        if existing is None:
            await self.repository.add_history(
                CatalogSlugHistory(id=new_id(), entity_type=entity_type, entity_id=entity_id, old_path=old_path)
            )

    async def _record_category_history(self, category: Category) -> None:
        await self._record_history(category.level, category.id, await self._category_path(category))
        categories = await self.repository.categories(active_only=False)
        if category.level == "category":
            children = [item for item in categories if item.parent_id == category.id]
        else:
            children = [category]
        for child in children:
            child_path = (
                f"/explore/{category.slug}/{child.slug}"
                if category.level == "category"
                else await self._category_path(child)
            )
            if child.id != category.id:
                await self._record_history("subcategory", child.id, child_path)
            for topic in await self.repository.topics(child.id, None, 10000, active_only=False):
                await self._record_history("topic", topic.id, f"{child_path}/{topic.slug}")

    def _category(self, row: Category) -> CatalogCategoryResponse:
        return CatalogCategoryResponse.model_validate(row)

    def _topic(self, row: Topic) -> CatalogTopicResponse:
        return CatalogTopicResponse.model_validate(row)

    async def _generation(self) -> str:
        key = self.redis.keys.key("catalog.generation", "global")
        value = await self.redis.get(key)
        return value.decode() if value is not None else "0"

    async def _cache_get[ModelT](self, part: str, model: type[ModelT]) -> ModelT | None:
        key = self.redis.keys.key("catalog.cache", await self._generation(), part)
        value = await self.redis.get(key)
        return TypeAdapter(model).validate_json(value) if value is not None else None

    async def _cache_set(self, part: str, value: object) -> None:
        key = self.redis.keys.key("catalog.cache", await self._generation(), part)
        if hasattr(value, "model_dump_json"):
            serialized = value.model_dump_json()
        elif isinstance(value, list):
            serialized = json.dumps(
                [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in value]
            )
        else:
            serialized = json.dumps(value)
        await self.redis.set(key, serialized, ttl=CACHE_TTL)

    def _changed(self, tags: set[str]) -> None:
        async def invalidate() -> None:
            await self.redis.increment(self.redis.keys.key("catalog.generation", "global"), ttl=CACHE_GENERATION_TTL)

        after_commit(self.session, invalidate)
        defer_revalidation(self.session, sorted(tags))
