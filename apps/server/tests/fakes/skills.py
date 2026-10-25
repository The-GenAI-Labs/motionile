from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID, uuid5

from motionile.engine.ai.llm.models import CallContext, Embedder
from motionile.engine.ai.ports import LoadedSkill, SkillLayer, SkillSummary
from motionile.engine.ai.scenes.style_tokens import parse_style_tokens
from motionile.engine.ai.skills.loader import SkillDocument

VERSION_NAMESPACE = UUID(int=0x5EED)


def cosine(first: Sequence[float], second: Sequence[float]) -> float:
    return sum(left * right for left, right in zip(first, second, strict=True))


@dataclass
class InMemorySkillCatalog:
    documents: tuple[SkillDocument, ...]
    vectors: dict[str, list[float]]
    unavailable: set[str] = field(default_factory=set[str])
    nearest_calls: list[tuple[SkillLayer, int]] = field(default_factory=list[tuple[SkillLayer, int]])
    by_slugs_calls: list[tuple[str, ...]] = field(default_factory=list[tuple[str, ...]])
    load_calls: list[tuple[str, ...]] = field(default_factory=list[tuple[str, ...]])

    @classmethod
    async def build(
        cls, documents: Sequence[SkillDocument], embedder: Embedder, context: CallContext
    ) -> "InMemorySkillCatalog":
        embedded = await embedder.embed([document.description for document in documents], context)
        return cls(
            documents=tuple(documents),
            vectors={document.slug: vector for document, vector in zip(documents, embedded, strict=True)},
        )

    def _summary(self, document: SkillDocument, similarity: float | None) -> SkillSummary:
        return SkillSummary(
            slug=document.slug,
            name=document.name,
            description=document.description,
            layer=document.layer,
            version_id=uuid5(VERSION_NAMESPACE, document.slug),
            token_count=document.token_count,
            similarity=similarity,
        )

    def _available(self) -> list[SkillDocument]:
        return [document for document in self.documents if document.slug not in self.unavailable]

    async def nearest(self, layer: SkillLayer, embedding: Sequence[float], limit: int) -> list[SkillSummary]:
        self.nearest_calls.append((layer, limit))
        scored = [
            (cosine(self.vectors[document.slug], embedding), document)
            for document in self._available()
            if document.layer is layer
        ]
        scored.sort(key=lambda item: (-item[0], item[1].slug))
        return [self._summary(document, score) for score, document in scored[:limit]]

    async def by_slugs(self, slugs: Sequence[str]) -> list[SkillSummary]:
        self.by_slugs_calls.append(tuple(slugs))
        wanted = set(slugs)
        return [self._summary(document, None) for document in self._available() if document.slug in wanted]

    async def load(self, slugs: Sequence[str]) -> list[LoadedSkill]:
        self.load_calls.append(tuple(slugs))
        available = {document.slug: document for document in self._available()}
        return [
            LoadedSkill(
                summary=self._summary(available[slug], None),
                body=available[slug].body,
                tokens=dict(parse_style_tokens(available[slug].tokens, slug=slug).properties)
                if available[slug].tokens
                else {},
                token_count=available[slug].token_count,
            )
            for slug in slugs
            if slug in available
        ]
