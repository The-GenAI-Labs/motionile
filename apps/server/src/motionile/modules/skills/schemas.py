from datetime import datetime

from motionile.core.schemas import CursorPage, PageQuery, ResponseModel
from motionile.engine.ai.ports import SkillLayer
from motionile.modules.skills.domain import EmbeddingStatus


class SkillVersionView(ResponseModel):
    number: int
    checksum: str
    created_at: datetime


class SkillView(ResponseModel):
    slug: str
    name: str
    description: str
    layer: SkillLayer
    version: int
    checksum: str
    token_count: int
    embedding_status: EmbeddingStatus
    updated_at: datetime


class SkillDetailView(SkillView):
    versions: list[SkillVersionView]


class SkillPage(CursorPage[SkillView]):
    pass


class SkillListQuery(PageQuery):
    layer: SkillLayer | None = None


class StyleView(ResponseModel):
    slug: str
    name: str
    description: str
    background: str
    surface: str
    text: str
    accent: str


class StyleListView(ResponseModel):
    items: list[StyleView]


class ReseedView(ResponseModel):
    created: int
    updated: int
    unchanged: int
    embedded: int
