import math
from collections.abc import Sequence
from functools import cache
from uuid import uuid5

from evals.prompts import PROMPT_NAMESPACE
from motionile.engine.ai.llm.models import CallContext, Embedder
from motionile.engine.ai.ports import LoadedSkill, SkillLayer, SkillSummary
from motionile.engine.ai.scenes.style_tokens import parse_style_tokens
from motionile.engine.ai.skills.loader import SkillDocument, load_library, token_count_of

CATALOG_CONTEXT = CallContext(user_id=PROMPT_NAMESPACE, job_id=None, stage="embed", call_key="eval-skill-catalog")


def summary_of(document: SkillDocument, similarity: float | None = None) -> SkillSummary:
    return SkillSummary(
        slug=document.slug,
        name=document.name,
        description=document.description,
        layer=document.layer,
        version_id=uuid5(PROMPT_NAMESPACE, f"skill:{document.slug}:{document.checksum.hex()}"),
        token_count=document.token_count,
        similarity=similarity,
    )


def loaded_of(document: SkillDocument) -> LoadedSkill:
    tokens = dict(parse_style_tokens(document.tokens, slug=document.slug).properties) if document.is_style else {}
    return LoadedSkill(
        summary=summary_of(document), body=document.body, tokens=tokens, token_count=token_count_of(document.body)
    )


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0


@cache
def library_documents() -> tuple[SkillDocument, ...]:
    return load_library()


def library_skill_bodies() -> list[LoadedSkill]:
    return [loaded_of(document) for document in library_documents()]


class LibrarySkillCatalog:
    def __init__(self, embedder: Embedder, documents: Sequence[SkillDocument] | None = None) -> None:
        self._embedder = embedder
        self._documents = tuple(documents if documents is not None else library_documents())
        self._by_slug = {document.slug: document for document in self._documents}
        self._vectors: dict[str, list[float]] = {}

    @property
    def documents(self) -> tuple[SkillDocument, ...]:
        return self._documents

    async def _ensure_vectors(self) -> None:
        if self._vectors:
            return
        texts = [f"{document.name} {document.description}" for document in self._documents]
        vectors = await self._embedder.embed(texts, CATALOG_CONTEXT)
        self._vectors = {document.slug: vector for document, vector in zip(self._documents, vectors, strict=True)}

    async def nearest(self, layer: SkillLayer, embedding: Sequence[float], limit: int) -> list[SkillSummary]:
        await self._ensure_vectors()
        scored = [
            (cosine(embedding, self._vectors[document.slug]), document)
            for document in self._documents
            if document.layer is layer
        ]
        ranked = sorted(scored, key=lambda pair: (-pair[0], pair[1].slug))
        return [summary_of(document, similarity) for similarity, document in ranked[:limit]]

    async def by_slugs(self, slugs: Sequence[str]) -> list[SkillSummary]:
        return [summary_of(self._by_slug[slug]) for slug in dict.fromkeys(slugs) if slug in self._by_slug]

    async def load(self, slugs: Sequence[str]) -> list[LoadedSkill]:
        return [loaded_of(self._by_slug[slug]) for slug in dict.fromkeys(slugs) if slug in self._by_slug]

    def bodies(self) -> list[LoadedSkill]:
        return [loaded_of(document) for document in self._documents]
