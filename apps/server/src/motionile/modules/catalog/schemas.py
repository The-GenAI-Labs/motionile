from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from motionile.core.schemas import CursorPage, PageQuery, ResponseModel, StrictModel

Slug = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")


class CatalogCategoryResponse(ResponseModel):
    id: UUID
    parent_id: UUID | None
    level: Literal["category", "subcategory"]
    slug: str
    name: str
    description: str | None
    icon: str | None
    sort_order: int
    is_active: bool
    version: int
    seo_title: str | None
    seo_description: str | None
    created_at: datetime
    updated_at: datetime


class CatalogTopicResponse(ResponseModel):
    id: UUID
    category_id: UUID
    slug: str
    title: str
    summary: str | None
    suggested_duration_ms: int
    difficulty: Literal["beginner", "intermediate", "advanced"]
    skill_hints: list[str]
    is_active: bool
    sort_order: int
    version: int
    seo_title: str | None
    seo_description: str | None
    created_at: datetime
    updated_at: datetime


class CategoryTreeItem(CatalogCategoryResponse):
    children: list[CatalogCategoryResponse]


class CatalogTreeResponse(ResponseModel):
    categories: list[CategoryTreeItem]


class AdminCatalogTreeResponse(CatalogTreeResponse):
    topics: list[CatalogTopicResponse]


class CategoryDetailResponse(ResponseModel):
    category: CatalogCategoryResponse
    subcategories: list[CatalogCategoryResponse]


class SubcategoryDetailResponse(ResponseModel):
    category: CatalogCategoryResponse
    subcategory: CatalogCategoryResponse
    topics: CursorPage[CatalogTopicResponse]


class TopicDetailResponse(ResponseModel):
    category: CatalogCategoryResponse
    subcategory: CatalogCategoryResponse
    topic: CatalogTopicResponse
    related_topics: list[CatalogTopicResponse]


class TopicSearchQuery(PageQuery):
    q: str = Field(min_length=2, max_length=120)


class TopicSearchResult(CatalogTopicResponse):
    path: str


class TopicSearchResponse(CursorPage[TopicSearchResult]):
    pass


class CatalogRedirectResponse(ResponseModel):
    destination: str


class CatalogPathResponse(ResponseModel):
    path: str
    last_modified: datetime


class CatalogPathsResponse(ResponseModel):
    items: list[CatalogPathResponse]


class CategoryWriteRequest(StrictModel):
    parent_id: UUID | None = None
    level: Literal["category", "subcategory"]
    slug: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    icon: str | None = Field(default=None, max_length=80)
    sort_order: int = Field(default=0, ge=0, le=100000)
    is_active: bool = True
    seo_title: str | None = Field(default=None, max_length=70)
    seo_description: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def valid_depth(self) -> "CategoryWriteRequest":
        if (self.level == "category") != (self.parent_id is None):
            raise ValueError("Categories have no parent and subcategories require one.")
        return self


class TopicWriteRequest(StrictModel):
    category_id: UUID
    slug: str = Slug
    title: str = Field(min_length=1, max_length=120)
    summary: str | None = Field(default=None, max_length=500)
    suggested_duration_ms: int = Field(default=60000, ge=10000, le=120000)
    difficulty: Literal["beginner", "intermediate", "advanced"] = "beginner"
    skill_hints: list[str] = Field(default_factory=list[str], max_length=20)
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0, le=100000)
    seo_title: str | None = Field(default=None, max_length=70)
    seo_description: str | None = Field(default=None, max_length=160)


class CategoryUpdateRequest(CategoryWriteRequest):
    version: int = Field(ge=1)


class TopicUpdateRequest(TopicWriteRequest):
    version: int = Field(ge=1)


class ReorderItem(StrictModel):
    id: UUID
    sort_order: int = Field(ge=0, le=100000)
    version: int = Field(ge=1)


class CatalogReorderRequest(StrictModel):
    entity_type: Literal["category", "topic"]
    items: list[ReorderItem] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_items(self) -> "CatalogReorderRequest":
        ids = [item.id for item in self.items]
        orders = [item.sort_order for item in self.items]
        if len(ids) != len(set(ids)) or len(orders) != len(set(orders)):
            raise ValueError("Reorder IDs and positions must be unique.")
        return self
