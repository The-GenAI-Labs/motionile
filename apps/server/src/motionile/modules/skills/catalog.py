from collections.abc import Sequence
from dataclasses import dataclass

from motionile.engine.ai.ports import LoadedSkill, SkillLayer, SkillSummary
from motionile.engine.ai.scenes.style_tokens import parse_style_tokens
from motionile.engine.ai.skills.loader import token_count_for, token_count_of
from motionile.modules.skills.repository import CatalogRow, SqlSkillRepository, StoreFactory, Transaction


@dataclass(frozen=True, slots=True)
class StyleOption:
    slug: str
    name: str
    description: str
    palette: dict[str, str]


def summary_of(row: CatalogRow) -> SkillSummary:
    return SkillSummary(
        slug=row.slug,
        name=row.name,
        description=row.description,
        layer=SkillLayer(row.layer),
        version_id=row.version_id,
        token_count=token_count_for(row.body_length),
        similarity=row.similarity,
    )


class DatabaseSkillCatalog:
    def __init__(self, transaction: Transaction, store_factory: StoreFactory = SqlSkillRepository) -> None:
        self._transaction = transaction
        self._store_factory = store_factory

    async def nearest(self, layer: SkillLayer, embedding: Sequence[float], limit: int) -> list[SkillSummary]:
        async with self._transaction() as session:
            rows = await self._store_factory(session).nearest(layer.value, embedding, limit)
        return [summary_of(row) for row in rows]

    async def by_slugs(self, slugs: Sequence[str]) -> list[SkillSummary]:
        async with self._transaction() as session:
            rows = await self._store_factory(session).by_slugs(list(dict.fromkeys(slugs)))
        return [summary_of(row) for row in rows]

    async def load(self, slugs: Sequence[str]) -> list[LoadedSkill]:
        wanted = list(dict.fromkeys(slugs))
        async with self._transaction() as session:
            rows = await self._store_factory(session).bodies(wanted)
        by_slug = {row.row.slug: row for row in rows}
        return [
            LoadedSkill(
                summary=summary_of(by_slug[slug].row),
                body=by_slug[slug].body,
                tokens=dict(parse_style_tokens(by_slug[slug].tokens, slug=slug).properties),
                token_count=token_count_of(by_slug[slug].body),
            )
            for slug in wanted
            if slug in by_slug
        ]

    async def style_exists(self, slug: str) -> bool:
        async with self._transaction() as session:
            return await self._store_factory(session).style_exists(slug)

    async def styles(self) -> list[StyleOption]:
        async with self._transaction() as session:
            rows = await self._store_factory(session).styles()
        return [
            StyleOption(
                slug=row.slug,
                name=row.name,
                description=row.description,
                palette=parse_style_tokens(row.tokens, slug=row.slug).palette,
            )
            for row in rows
        ]
