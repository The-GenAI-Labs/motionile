from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.ids import new_id
from motionile.core.pagination import Cursor
from motionile.modules.skills.repository import (
    BodyRow,
    CatalogRow,
    NewSkill,
    NewSkillVersion,
    SkillRecord,
    SkillState,
    StyleRow,
    VersionRecord,
)

EPOCH = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def cosine(first: Sequence[float], second: Sequence[float]) -> float:
    return sum(left * right for left, right in zip(first, second, strict=True))


@dataclass
class StoredSkill:
    id: UUID
    slug: str
    name: str
    description: str
    current_version_id: UUID | None
    created_at: datetime
    updated_at: datetime
    is_enabled: bool = True
    status: str = "active"


@dataclass
class StoredVersion:
    id: UUID
    skill_id: UUID
    number: int
    body: str
    frontmatter: dict[str, Any]
    checksum: bytes
    created_at: datetime


@dataclass
class SkillWorld:
    skills: dict[UUID, StoredSkill] = field(default_factory=dict[UUID, StoredSkill])
    versions: dict[UUID, StoredVersion] = field(default_factory=dict[UUID, StoredVersion])
    embeddings: dict[UUID, tuple[list[float], str]] = field(default_factory=dict[UUID, tuple[list[float], str]])
    locks: list[str] = field(default_factory=list[str])
    transactions: int = 0
    tick: int = 0

    def next_time(self) -> datetime:
        self.tick += 1
        return EPOCH + timedelta(seconds=self.tick)

    def by_slug(self, slug: str) -> StoredSkill | None:
        return next((skill for skill in self.skills.values() if skill.slug == slug), None)

    def current_version(self, skill: StoredSkill) -> StoredVersion | None:
        return self.versions.get(skill.current_version_id) if skill.current_version_id is not None else None

    def version_numbers(self, slug: str) -> list[int]:
        skill = self.by_slug(slug)
        if skill is None:
            return []
        return sorted(version.number for version in self.versions.values() if version.skill_id == skill.id)

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession]:
        self.transactions += 1
        yield AsyncSession()

    def store(self, session: AsyncSession) -> "InMemorySkillStore":
        del session
        return InMemorySkillStore(self)


class InMemorySkillStore:
    def __init__(self, world: SkillWorld) -> None:
        self._world = world

    async def lock(self, slug: str) -> None:
        self._world.locks.append(slug)

    def _state(self, skill: StoredSkill) -> SkillState:
        version = self._world.current_version(skill)
        embedding = self._world.embeddings.get(version.id) if version is not None else None
        return SkillState(
            skill_id=skill.id,
            version_id=version.id if version is not None else None,
            version=version.number if version is not None else None,
            checksum=version.checksum if version is not None else None,
            embedding_model=embedding[1] if embedding is not None else None,
        )

    async def states(self) -> dict[str, SkillState]:
        return {skill.slug: self._state(skill) for skill in self._world.skills.values()}

    async def state_of(self, slug: str) -> SkillState | None:
        skill = self._world.by_slug(slug)
        return self._state(skill) if skill is not None else None

    async def latest_number(self, skill_id: UUID) -> int:
        numbers = [version.number for version in self._world.versions.values() if version.skill_id == skill_id]
        return max(numbers, default=0)

    async def insert_skill(self, row: NewSkill) -> UUID:
        now = self._world.next_time()
        skill = StoredSkill(new_id(), row.slug, row.name, row.description, None, now, now)
        self._world.skills[skill.id] = skill
        return skill.id

    async def insert_version(self, row: NewSkillVersion) -> UUID:
        version = StoredVersion(
            new_id(), row.skill_id, row.number, row.body, row.frontmatter, row.checksum, self._world.next_time()
        )
        self._world.versions[version.id] = version
        return version.id

    async def point_to_version(self, skill_id: UUID, version_id: UUID, name: str, description: str) -> None:
        skill = self._world.skills[skill_id]
        skill.current_version_id = version_id
        skill.name = name
        skill.description = description
        skill.updated_at = self._world.next_time()

    async def upsert_embedding(self, version_id: UUID, vector: Sequence[float], model: str) -> None:
        self._world.embeddings[version_id] = (list(vector), model)

    def _record(self, skill: StoredSkill) -> SkillRecord | None:
        version = self._world.current_version(skill)
        if version is None:
            return None
        embedding = self._world.embeddings.get(version.id)
        return SkillRecord(
            id=skill.id,
            slug=skill.slug,
            name=skill.name,
            description=skill.description,
            layer=str(version.frontmatter["metadata"]["layer"]),
            version=version.number,
            checksum=version.checksum,
            body_length=len(version.body),
            embedding_model=embedding[1] if embedding is not None else None,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
        )

    async def page(self, layer: str | None, cursor: Cursor | None, limit: int) -> list[SkillRecord]:
        records = [record for skill in self._world.skills.values() if (record := self._record(skill)) is not None]
        records = [record for record in records if layer is None or record.layer == layer]
        records.sort(key=lambda record: (record.created_at, record.id), reverse=True)
        if cursor is not None:
            records = [record for record in records if (record.created_at, record.id) < (cursor.created_at, cursor.id)]
        return records[: limit + 1]

    async def record_of(self, slug: str) -> SkillRecord | None:
        skill = self._world.by_slug(slug)
        return self._record(skill) if skill is not None else None

    async def versions_of(self, skill_id: UUID) -> list[VersionRecord]:
        versions = [version for version in self._world.versions.values() if version.skill_id == skill_id]
        return [
            VersionRecord(version.number, version.checksum, version.created_at)
            for version in sorted(versions, key=lambda version: version.number, reverse=True)
        ]

    def _servable(self) -> list[tuple[StoredSkill, StoredVersion]]:
        pairs = [(skill, self._world.current_version(skill)) for skill in self._world.skills.values()]
        return [
            (skill, version)
            for skill, version in pairs
            if version is not None and skill.status == "active" and skill.is_enabled
        ]

    @staticmethod
    def _row(skill: StoredSkill, version: StoredVersion, similarity: float | None) -> CatalogRow:
        return CatalogRow(
            slug=skill.slug,
            name=skill.name,
            description=skill.description,
            layer=str(version.frontmatter["metadata"]["layer"]),
            version_id=version.id,
            body_length=len(version.body),
            similarity=similarity,
        )

    async def nearest(self, layer: str, embedding: Sequence[float], limit: int) -> list[CatalogRow]:
        scored = [
            (cosine(self._world.embeddings[version.id][0], embedding), skill, version)
            for skill, version in self._servable()
            if version.frontmatter["metadata"]["layer"] == layer and version.id in self._world.embeddings
        ]
        scored.sort(key=lambda item: (-item[0], item[1].slug))
        return [self._row(skill, version, score) for score, skill, version in scored[:limit]]

    async def by_slugs(self, slugs: Sequence[str]) -> list[CatalogRow]:
        wanted = set(slugs)
        pairs = sorted(self._servable(), key=lambda pair: pair[0].slug)
        return [self._row(skill, version, None) for skill, version in pairs if skill.slug in wanted]

    async def bodies(self, slugs: Sequence[str]) -> list[BodyRow]:
        wanted = set(slugs)
        pairs = sorted(self._servable(), key=lambda pair: pair[0].slug)
        return [
            BodyRow(
                row=self._row(skill, version, None),
                body=version.body,
                tokens=str(version.frontmatter["metadata"].get("tokens", "")),
            )
            for skill, version in pairs
            if skill.slug in wanted
        ]

    async def styles(self) -> list[StyleRow]:
        return sorted(
            (
                StyleRow(
                    skill.slug,
                    skill.name,
                    skill.description,
                    str(version.frontmatter["metadata"].get("tokens", "")),
                )
                for skill, version in self._servable()
                if version.frontmatter["metadata"]["layer"] == "style"
            ),
            key=lambda row: row.slug,
        )

    async def style_exists(self, slug: str) -> bool:
        return any(
            skill.slug == slug and version.frontmatter["metadata"]["layer"] == "style"
            for skill, version in self._servable()
        )


def disabled(world: SkillWorld, slug: str) -> None:
    skill = world.by_slug(slug)
    assert skill is not None
    world.skills[skill.id] = replace(skill, is_enabled=False)
