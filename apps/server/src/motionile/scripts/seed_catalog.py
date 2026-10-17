import argparse
import asyncio
import re
from pathlib import Path
from uuid import UUID

import yaml
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.config import get_settings
from motionile.core.ids import new_id
from motionile.core.resources import build_resources
from motionile.modules.catalog import Category, Topic

DEFAULT_SEED = Path(__file__).resolve().parents[3] / "seeds" / "catalog.yaml"


class SeedSubcategory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    description: str
    topics: list[str] = Field(min_length=6, max_length=10)


class SeedCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    description: str
    subcategories: list[SeedSubcategory]


class SeedCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    categories: list[SeedCategory]


def parse_catalog(source: str) -> SeedCatalog:
    return TypeAdapter(SeedCatalog).validate_python(yaml.safe_load(source))


def topic_slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")


async def category_by_slug(session: AsyncSession, parent_id: UUID | None, slug: str) -> Category | None:
    condition = Category.parent_id.is_(None) if parent_id is None else Category.parent_id == parent_id
    return await session.scalar(select(Category).where(condition, Category.slug == slug))


async def seed(path: Path) -> tuple[int, int]:
    source = await asyncio.to_thread(path.read_text, encoding="utf-8")
    parsed = parse_catalog(source)
    resources = build_resources(get_settings(), application_name="motionile-seed-catalog")
    categories_created = 0
    topics_created = 0
    try:
        async with resources.database.transaction() as session:
            for category_order, category_seed in enumerate(parsed.categories):
                category = await category_by_slug(session, None, category_seed.slug)
                if category is None:
                    category = Category(
                        id=new_id(),
                        parent_id=None,
                        level="category",
                        slug=category_seed.slug,
                        name=category_seed.name,
                        description=category_seed.description,
                        icon=None,
                        sort_order=category_order,
                        is_active=True,
                        seo_title=f"{category_seed.name} Explainer Topics",
                        seo_description=category_seed.description,
                    )
                    session.add(category)
                    await session.flush()
                    categories_created += 1
                for subcategory_order, subcategory_seed in enumerate(category_seed.subcategories):
                    subcategory = await category_by_slug(session, category.id, subcategory_seed.slug)
                    if subcategory is None:
                        subcategory = Category(
                            id=new_id(),
                            parent_id=category.id,
                            level="subcategory",
                            slug=subcategory_seed.slug,
                            name=subcategory_seed.name,
                            description=subcategory_seed.description,
                            icon=None,
                            sort_order=subcategory_order,
                            is_active=True,
                            seo_title=f"{subcategory_seed.name} Explainer Topics",
                            seo_description=subcategory_seed.description,
                        )
                        session.add(subcategory)
                        await session.flush()
                        categories_created += 1
                    for topic_order, topic_title in enumerate(subcategory_seed.topics):
                        slug = topic_slug(topic_title)
                        exists = await session.scalar(
                            select(Topic.id).where(Topic.category_id == subcategory.id, Topic.slug == slug)
                        )
                        if exists is not None:
                            continue
                        session.add(
                            Topic(
                                id=new_id(),
                                category_id=subcategory.id,
                                slug=slug,
                                title=topic_title,
                                summary=(
                                    f"A visual introduction to {topic_title}, covering its core model, key terms, "
                                    "and a practical example that connects the idea to real problem solving."
                                ),
                                suggested_duration_ms=60000,
                                difficulty="beginner",
                                skill_hints=[subcategory_seed.slug],
                                is_active=True,
                                sort_order=topic_order,
                                seo_title=f"{topic_title} Explained Visually"[:70],
                                seo_description=(
                                    f"Learn {topic_title} with a concise animated guide to the core ideas, "
                                    "important terms, and a practical example."
                                )[:160],
                            )
                        )
                        topics_created += 1
            await session.flush()
    finally:
        await resources.aclose()
    return categories_created, topics_created


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Insert missing starter catalog records without changing existing rows."
    )
    parser.add_argument("--file", type=Path, default=DEFAULT_SEED)
    arguments = parser.parse_args(argv)
    categories, topics = asyncio.run(seed(arguments.file))
    print(f"Created {categories} categories and {topics} topics.")


if __name__ == "__main__":
    main()
