from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from motionile.modules.catalog.models import Category, Topic


@dataclass(frozen=True, slots=True)
class TopicBrief:
    id: UUID
    title: str
    summary: str | None
    category: str
    subcategory: str
    skill_hints: tuple[str, ...]
    suggested_duration_ms: int


async def published_topic(session: AsyncSession, topic_id: UUID) -> TopicBrief | None:
    subcategory = aliased(Category)
    category = aliased(Category)
    statement = (
        select(Topic, subcategory.name, category.name)
        .join(subcategory, subcategory.id == Topic.category_id)
        .join(category, category.id == subcategory.parent_id)
        .where(
            Topic.id == topic_id,
            Topic.is_active.is_(True),
            subcategory.is_active.is_(True),
            category.is_active.is_(True),
        )
        .execution_options(populate_existing=True)
    )
    found = (await session.execute(statement)).first()
    if found is None:
        return None
    topic, subcategory_name, category_name = found
    return TopicBrief(
        id=topic.id,
        title=topic.title,
        summary=topic.summary,
        category=category_name,
        subcategory=subcategory_name,
        skill_hints=tuple(topic.skill_hints),
        suggested_duration_ms=topic.suggested_duration_ms,
    )
