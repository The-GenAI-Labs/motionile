from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from motionile.core.pagination import Cursor, keyset_page
from motionile.modules.catalog.models import CatalogSlugHistory, Category, Topic

MINIMUM_SEARCH_SIMILARITY = 0.1


class CatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def categories(self, *, active_only: bool = True) -> list[Category]:
        query = select(Category)
        if active_only:
            query = query.where(Category.is_active.is_(True))
        return list(await self.session.scalars(query.order_by(Category.level, Category.sort_order, Category.id)))

    async def category(self, category_id: UUID, *, lock: bool = False) -> Category | None:
        query = select(Category).where(Category.id == category_id)
        if lock:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def top_by_slug(self, slug: str, *, active_only: bool = True) -> Category | None:
        query = select(Category).where(Category.level == "category", Category.slug == slug)
        if active_only:
            query = query.where(Category.is_active.is_(True))
        return await self.session.scalar(query)

    async def subcategory_by_slug(self, parent_id: UUID, slug: str, *, active_only: bool = True) -> Category | None:
        query = select(Category).where(
            Category.level == "subcategory", Category.parent_id == parent_id, Category.slug == slug
        )
        if active_only:
            query = query.where(Category.is_active.is_(True))
        return await self.session.scalar(query)

    async def topic(self, topic_id: UUID, *, lock: bool = False) -> Topic | None:
        query = select(Topic).where(Topic.id == topic_id)
        if lock:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def topic_by_slug(self, category_id: UUID, slug: str, *, active_only: bool = True) -> Topic | None:
        query = select(Topic).where(Topic.category_id == category_id, Topic.slug == slug)
        if active_only:
            query = query.where(Topic.is_active.is_(True))
        return await self.session.scalar(query)

    async def topics(
        self, category_id: UUID, cursor: Cursor | None, limit: int, *, active_only: bool = True
    ) -> list[Topic]:
        query = select(Topic).where(Topic.category_id == category_id)
        if active_only:
            query = query.where(Topic.is_active.is_(True))
        query = keyset_page(query, created_at=Topic.created_at, id_=Topic.id, cursor=cursor, limit=limit)
        return list(await self.session.scalars(query))

    async def all_topics(self) -> list[Topic]:
        query = select(Topic).order_by(Topic.category_id, Topic.sort_order, Topic.id)
        return list(await self.session.scalars(query))

    async def related(self, topic: Topic, limit: int = 4) -> list[Topic]:
        query = (
            select(Topic)
            .where(Topic.category_id == topic.category_id, Topic.id != topic.id, Topic.is_active.is_(True))
            .order_by(func.abs(Topic.sort_order - topic.sort_order), Topic.id)
            .limit(limit)
        )
        return list(await self.session.scalars(query))

    async def search(self, query_text: str, limit: int) -> list[Topic]:
        parent = aliased(Category)
        score = func.greatest(
            func.similarity(Topic.title, query_text),
            func.similarity(func.coalesce(Topic.summary, ""), query_text),
        )
        query = (
            select(Topic)
            .join(Category, Category.id == Topic.category_id)
            .join(parent, parent.id == Category.parent_id)
            .where(
                Topic.is_active.is_(True),
                Category.is_active.is_(True),
                parent.is_active.is_(True),
                or_(score >= MINIMUM_SEARCH_SIMILARITY, Topic.title.ilike(f"%{query_text}%")),
            )
            .order_by(score.desc(), Topic.title)
            .limit(limit)
        )
        return list(await self.session.scalars(query))

    async def redirect(self, old_path: str) -> CatalogSlugHistory | None:
        return await self.session.scalar(select(CatalogSlugHistory).where(CatalogSlugHistory.old_path == old_path))

    async def history_for(self, entity_type: str, entity_id: UUID) -> list[CatalogSlugHistory]:
        return list(
            await self.session.scalars(
                select(CatalogSlugHistory).where(
                    CatalogSlugHistory.entity_type == entity_type, CatalogSlugHistory.entity_id == entity_id
                )
            )
        )

    async def create_category(self, category: Category) -> None:
        self.session.add(category)
        await self.session.flush()

    async def create_topic(self, topic: Topic) -> None:
        self.session.add(topic)
        await self.session.flush()

    async def reorder_categories(self, positions: dict[UUID, tuple[int, int]]) -> int:
        count = 0
        for entity_id, (position, version) in positions.items():
            result = await self.session.execute(
                update(Category)
                .where(Category.id == entity_id, Category.version == version)
                .values(sort_order=position, version=Category.version + 1)
                .returning(Category.id)
            )
            count += result.scalar_one_or_none() is not None
        return count

    async def reorder_topics(self, positions: dict[UUID, tuple[int, int]]) -> int:
        count = 0
        for entity_id, (position, version) in positions.items():
            result = await self.session.execute(
                update(Topic)
                .where(Topic.id == entity_id, Topic.version == version)
                .values(sort_order=position, version=Topic.version + 1)
                .returning(Topic.id)
            )
            count += result.scalar_one_or_none() is not None
        return count

    async def paths(self) -> list[tuple[Category, Category | None, Topic | None]]:
        categories = await self.categories()
        top = [category for category in categories if category.level == "category"]
        subcategories = [category for category in categories if category.level == "subcategory"]
        rows: list[tuple[Category, Category | None, Topic | None]] = [(category, None, None) for category in top]
        by_id = {category.id: category for category in top}
        for subcategory in subcategories:
            if subcategory.parent_id is None:
                continue
            parent = by_id.get(subcategory.parent_id)
            if parent is None:
                continue
            rows.append((parent, subcategory, None))
            topics = list(
                await self.session.scalars(
                    select(Topic)
                    .where(Topic.category_id == subcategory.id, Topic.is_active.is_(True))
                    .order_by(Topic.sort_order, Topic.id)
                )
            )
            rows.extend((parent, subcategory, topic) for topic in topics)
        return rows

    async def add_history(self, row: CatalogSlugHistory) -> None:
        self.session.add(row)
        await self.session.flush()

    async def delete_category(self, category: Category) -> None:
        await self.session.delete(category)

    async def delete_topic(self, topic: Topic) -> None:
        await self.session.delete(topic)
