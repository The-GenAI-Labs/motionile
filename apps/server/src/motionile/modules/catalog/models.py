from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from motionile.core.db import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Category(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("parent_id", "slug", name="uq_categories_parent_id_slug", postgresql_nulls_not_distinct=True),
        CheckConstraint("level IN ('category', 'subcategory')", name="level"),
        CheckConstraint(
            "(level = 'category' AND parent_id IS NULL) OR (level = 'subcategory' AND parent_id IS NOT NULL)",
            name="level_parent",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND char_length(slug) <= 80", name="slug_format"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="name_length"),
        CheckConstraint("description IS NULL OR char_length(description) <= 500", name="description_length"),
        CheckConstraint("seo_title IS NULL OR char_length(seo_title) <= 70", name="seo_title_length"),
        CheckConstraint(
            "seo_description IS NULL OR char_length(seo_description) <= 160", name="seo_description_length"
        ),
        Index("ix_categories_parent_id_sort_order", "parent_id", "sort_order", postgresql_where=text("is_active")),
    )

    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    level: Mapped[str]
    slug: Mapped[str]
    name: Mapped[str]
    description: Mapped[str | None]
    icon: Mapped[str | None]
    sort_order: Mapped[int] = mapped_column(server_default="0")
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    version: Mapped[int] = mapped_column(server_default="1")
    seo_title: Mapped[str | None]
    seo_description: Mapped[str | None]


class Topic(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "topics"
    __table_args__ = (
        UniqueConstraint("category_id", "slug"),
        CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND char_length(slug) <= 120", name="slug_format"),
        CheckConstraint("suggested_duration_ms BETWEEN 10000 AND 120000", name="suggested_duration_ms_range"),
        CheckConstraint("difficulty IN ('beginner', 'intermediate', 'advanced')", name="difficulty"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("char_length(title) BETWEEN 1 AND 120", name="title_length"),
        CheckConstraint("summary IS NULL OR char_length(summary) <= 500", name="summary_length"),
        CheckConstraint("seo_title IS NULL OR char_length(seo_title) <= 70", name="seo_title_length"),
        CheckConstraint(
            "seo_description IS NULL OR char_length(seo_description) <= 160", name="seo_description_length"
        ),
        Index("ix_topics_category_id_sort_order", "category_id", "sort_order", postgresql_where=text("is_active")),
        Index("ix_topics_title_trgm", "title", postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"}),
        Index("ix_topics_summary_trgm", "summary", postgresql_using="gin", postgresql_ops={"summary": "gin_trgm_ops"}),
    )

    category_id: Mapped[UUID] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    slug: Mapped[str]
    title: Mapped[str]
    summary: Mapped[str | None]
    suggested_duration_ms: Mapped[int] = mapped_column(server_default="60000")
    difficulty: Mapped[str] = mapped_column(server_default="beginner")
    skill_hints: Mapped[list[str]] = mapped_column(ARRAY(Text()), server_default=text("'{}'"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(server_default="0")
    version: Mapped[int] = mapped_column(server_default="1")
    seo_title: Mapped[str | None]
    seo_description: Mapped[str | None]


class CatalogSlugHistory(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "catalog_slug_history"
    __table_args__ = (
        CheckConstraint("entity_type IN ('category', 'subcategory', 'topic')", name="entity_type"),
        CheckConstraint("old_path ~ '^/explore/[a-z0-9-]+(/[a-z0-9-]+){0,2}$'", name="old_path_format"),
        Index("ix_catalog_slug_history_entity", "entity_type", "entity_id"),
    )

    entity_type: Mapped[str]
    entity_id: Mapped[UUID]
    old_path: Mapped[str] = mapped_column(unique=True)
