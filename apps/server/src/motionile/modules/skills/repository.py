from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Protocol, cast
from uuid import UUID

from sqlalchemy import ColumnElement, Float, Select, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.ids import new_id
from motionile.core.pagination import Cursor, keyset_page
from motionile.modules.skills.models import Skill, SkillEmbedding, SkillVersion

SYSTEM_VISIBILITY: Final = "system"
ACTIVE_STATUS: Final = "active"
PASSED_SCAN: Final = "passed"
SEED_LOCK_NAMESPACE: Final = "skills.seed"
METADATA_KEY: Final = "metadata"
LAYER_KEY: Final = "layer"
TOKENS_KEY: Final = "tokens"
COSINE_DISTANCE: Final = "<=>"

type Transaction = Callable[[], AbstractAsyncContextManager[AsyncSession]]
type StoreFactory = Callable[[AsyncSession], SkillStore]


@dataclass(frozen=True, slots=True)
class SkillState:
    skill_id: UUID
    version_id: UUID | None
    version: int | None
    checksum: bytes | None
    embedding_model: str | None


@dataclass(frozen=True, slots=True)
class NewSkill:
    slug: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class NewSkillVersion:
    skill_id: UUID
    number: int
    body: str
    frontmatter: dict[str, Any]
    checksum: bytes
    scanned_at: datetime


@dataclass(frozen=True, slots=True)
class SkillRecord:
    id: UUID
    slug: str
    name: str
    description: str
    layer: str
    version: int
    checksum: bytes
    body_length: int
    embedding_model: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class VersionRecord:
    version: int
    checksum: bytes
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CatalogRow:
    slug: str
    name: str
    description: str
    layer: str
    version_id: UUID
    body_length: int
    similarity: float | None


@dataclass(frozen=True, slots=True)
class BodyRow:
    row: CatalogRow
    body: str
    tokens: str


class SkillStore(Protocol):
    async def lock(self, slug: str) -> None: ...

    async def states(self) -> dict[str, SkillState]: ...

    async def state_of(self, slug: str) -> SkillState | None: ...

    async def latest_number(self, skill_id: UUID) -> int: ...

    async def insert_skill(self, row: NewSkill) -> UUID: ...

    async def insert_version(self, row: NewSkillVersion) -> UUID: ...

    async def point_to_version(self, skill_id: UUID, version_id: UUID, name: str, description: str) -> None: ...

    async def upsert_embedding(self, version_id: UUID, vector: Sequence[float], model: str) -> None: ...

    async def page(self, layer: str | None, cursor: Cursor | None, limit: int) -> list[SkillRecord]: ...

    async def record_of(self, slug: str) -> SkillRecord | None: ...

    async def versions_of(self, skill_id: UUID) -> list[VersionRecord]: ...

    async def nearest(self, layer: str, embedding: Sequence[float], limit: int) -> list[CatalogRow]: ...

    async def by_slugs(self, slugs: Sequence[str]) -> list[CatalogRow]: ...

    async def bodies(self, slugs: Sequence[str]) -> list[BodyRow]: ...

    async def style_exists(self, slug: str) -> bool: ...


def layer_of_version() -> ColumnElement[str]:
    return func.jsonb_extract_path_text(SkillVersion.frontmatter, METADATA_KEY, LAYER_KEY)


def tokens_of_version() -> ColumnElement[str]:
    return func.jsonb_extract_path_text(SkillVersion.frontmatter, METADATA_KEY, TOKENS_KEY)


def system_skill_filters() -> tuple[ColumnElement[bool], ...]:
    return (
        Skill.visibility == SYSTEM_VISIBILITY,
        Skill.owner_user_id.is_(None),
        Skill.deleted_at.is_(None),
    )


def servable_skill_filters() -> tuple[ColumnElement[bool], ...]:
    return (*system_skill_filters(), Skill.status == ACTIVE_STATUS, Skill.is_enabled.is_(True))


def catalog_row(values: Any, similarity: float | None) -> CatalogRow:
    return CatalogRow(
        slug=values.slug,
        name=values.name,
        description=values.description,
        layer=values.layer,
        version_id=values.version_id,
        body_length=values.body_length,
        similarity=similarity,
    )


class SqlSkillRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock(self, slug: str) -> None:
        await self._session.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"{SEED_LOCK_NAMESPACE}:{slug}"))))

    def _states_statement(self) -> Select[*tuple[Any, ...]]:
        return (
            select(
                Skill.id,
                Skill.slug,
                Skill.current_version_id,
                SkillVersion.version,
                SkillVersion.checksum,
                SkillEmbedding.model,
            )
            .select_from(Skill)
            .outerjoin(SkillVersion, SkillVersion.id == Skill.current_version_id)
            .outerjoin(SkillEmbedding, SkillEmbedding.skill_version_id == Skill.current_version_id)
            .where(*system_skill_filters())
        )

    async def states(self) -> dict[str, SkillState]:
        result = await self._session.execute(self._states_statement())
        return {
            row.slug: SkillState(row.id, row.current_version_id, row.version, row.checksum, row.model) for row in result
        }

    async def state_of(self, slug: str) -> SkillState | None:
        result = await self._session.execute(self._states_statement().where(Skill.slug == slug))
        row = result.first()
        if row is None:
            return None
        return SkillState(row.id, row.current_version_id, row.version, row.checksum, row.model)

    async def latest_number(self, skill_id: UUID) -> int:
        highest = await self._session.scalar(
            select(func.max(SkillVersion.version)).where(SkillVersion.skill_id == skill_id)
        )
        return highest or 0

    async def insert_skill(self, row: NewSkill) -> UUID:
        skill = Skill(
            id=new_id(),
            owner_user_id=None,
            slug=row.slug,
            name=row.name,
            description=row.description,
            visibility=SYSTEM_VISIBILITY,
            status=ACTIVE_STATUS,
            is_enabled=True,
        )
        self._session.add(skill)
        await self._session.flush()
        return skill.id

    async def insert_version(self, row: NewSkillVersion) -> UUID:
        version = SkillVersion(
            id=new_id(),
            skill_id=row.skill_id,
            version=row.number,
            body_md=row.body,
            frontmatter=row.frontmatter,
            checksum=row.checksum,
            scan_status=PASSED_SCAN,
            scanned_at=row.scanned_at,
            created_by=None,
        )
        self._session.add(version)
        await self._session.flush()
        return version.id

    async def point_to_version(self, skill_id: UUID, version_id: UUID, name: str, description: str) -> None:
        skill = await self._session.get(Skill, skill_id, populate_existing=True)
        if skill is None:
            return
        skill.current_version_id = version_id
        skill.name = name
        skill.description = description
        await self._session.flush()

    async def upsert_embedding(self, version_id: UUID, vector: Sequence[float], model: str) -> None:
        statement = pg_insert(SkillEmbedding).values(skill_version_id=version_id, embedding=list(vector), model=model)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[SkillEmbedding.skill_version_id],
                set_={
                    "embedding": statement.excluded.embedding,
                    "model": statement.excluded.model,
                    "updated_at": func.now(),
                },
            )
        )

    def _records_statement(self) -> Select[*tuple[Any, ...]]:
        return (
            select(
                Skill.id,
                Skill.slug,
                Skill.name,
                Skill.description,
                layer_of_version().label("layer"),
                SkillVersion.version,
                SkillVersion.checksum,
                func.char_length(SkillVersion.body_md).label("body_length"),
                SkillEmbedding.model,
                Skill.created_at,
                Skill.updated_at,
            )
            .select_from(Skill)
            .join(SkillVersion, SkillVersion.id == Skill.current_version_id)
            .outerjoin(SkillEmbedding, SkillEmbedding.skill_version_id == SkillVersion.id)
            .where(*system_skill_filters())
        )

    @staticmethod
    def _record(row: Any) -> SkillRecord:
        return SkillRecord(
            id=row.id,
            slug=row.slug,
            name=row.name,
            description=row.description,
            layer=row.layer,
            version=row.version,
            checksum=bytes(row.checksum),
            body_length=row.body_length,
            embedding_model=row.model,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def page(self, layer: str | None, cursor: Cursor | None, limit: int) -> list[SkillRecord]:
        statement = self._records_statement()
        if layer is not None:
            statement = statement.where(layer_of_version() == layer)
        statement = keyset_page(statement, created_at=Skill.created_at, id_=Skill.id, cursor=cursor, limit=limit)
        return [self._record(row) for row in await self._session.execute(statement)]

    async def record_of(self, slug: str) -> SkillRecord | None:
        row = (await self._session.execute(self._records_statement().where(Skill.slug == slug))).first()
        return self._record(row) if row is not None else None

    async def versions_of(self, skill_id: UUID) -> list[VersionRecord]:
        statement = (
            select(SkillVersion.version, SkillVersion.checksum, SkillVersion.created_at)
            .where(SkillVersion.skill_id == skill_id)
            .order_by(SkillVersion.version.desc())
        )
        return [
            VersionRecord(row.version, bytes(row.checksum), row.created_at)
            for row in await self._session.execute(statement)
        ]

    def _catalog_statement(self, *extra: ColumnElement[Any]) -> Select[*tuple[Any, ...]]:
        return (
            select(
                Skill.slug,
                Skill.name,
                Skill.description,
                layer_of_version().label("layer"),
                SkillVersion.id.label("version_id"),
                func.char_length(SkillVersion.body_md).label("body_length"),
                *extra,
            )
            .select_from(Skill)
            .join(SkillVersion, SkillVersion.id == Skill.current_version_id)
            .where(*servable_skill_filters())
        )

    async def nearest(self, layer: str, embedding: Sequence[float], limit: int) -> list[CatalogRow]:
        distance = cast(
            "ColumnElement[float]", SkillEmbedding.embedding.op(COSINE_DISTANCE, return_type=Float)(list(embedding))
        )
        statement = (
            self._catalog_statement(distance.label("distance"))
            .join(SkillEmbedding, SkillEmbedding.skill_version_id == SkillVersion.id)
            .where(layer_of_version() == layer)
            .order_by(distance, Skill.slug)
            .limit(limit)
        )
        return [catalog_row(row, 1.0 - float(row.distance)) for row in await self._session.execute(statement)]

    async def by_slugs(self, slugs: Sequence[str]) -> list[CatalogRow]:
        if not slugs:
            return []
        statement = self._catalog_statement().where(Skill.slug.in_(list(slugs))).order_by(Skill.slug)
        return [catalog_row(row, None) for row in await self._session.execute(statement)]

    async def bodies(self, slugs: Sequence[str]) -> list[BodyRow]:
        if not slugs:
            return []
        statement = (
            self._catalog_statement(SkillVersion.body_md.label("body"), tokens_of_version().label("tokens"))
            .where(Skill.slug.in_(list(slugs)))
            .order_by(Skill.slug)
        )
        return [
            BodyRow(row=catalog_row(row, None), body=row.body, tokens=row.tokens or "")
            for row in await self._session.execute(statement)
        ]

    async def style_exists(self, slug: str) -> bool:
        statement = (
            select(Skill.id)
            .join(SkillVersion, SkillVersion.id == Skill.current_version_id)
            .where(*servable_skill_filters(), Skill.slug == slug, layer_of_version() == "style")
            .limit(1)
        )
        return await self._session.scalar(statement) is not None
