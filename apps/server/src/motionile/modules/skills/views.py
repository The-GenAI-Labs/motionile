from motionile.engine.ai.ports import SkillLayer
from motionile.engine.ai.skills.loader import token_count_for
from motionile.modules.skills.domain import checksum_prefix, embedding_status
from motionile.modules.skills.repository import SkillRecord, VersionRecord
from motionile.modules.skills.schemas import SkillDetailView, SkillVersionView, SkillView


def skill_view(record: SkillRecord, expected_model: str) -> SkillView:
    return SkillView(
        slug=record.slug,
        name=record.name,
        description=record.description,
        layer=SkillLayer(record.layer),
        version=record.version,
        checksum=checksum_prefix(record.checksum),
        token_count=token_count_for(record.body_length),
        embedding_status=embedding_status(record.embedding_model, expected_model),
        updated_at=record.updated_at,
    )


def version_view(record: VersionRecord) -> SkillVersionView:
    return SkillVersionView(
        number=record.version, checksum=checksum_prefix(record.checksum), created_at=record.created_at
    )


def detail_view(record: SkillRecord, versions: list[VersionRecord], expected_model: str) -> SkillDetailView:
    return SkillDetailView(
        **skill_view(record, expected_model).model_dump(),
        versions=[version_view(version) for version in versions],
    )
