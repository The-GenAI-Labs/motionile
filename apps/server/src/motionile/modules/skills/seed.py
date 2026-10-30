from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import Clock
from motionile.core.ids import new_id
from motionile.engine.ai.llm.models import CallContext, Embedder
from motionile.engine.ai.skills.loader import SkillDocument
from motionile.modules.audit import ActorType, AuditEvent
from motionile.modules.audit import record as record_audit
from motionile.modules.skills.domain import AUDIT_TARGET, SkillAction, checksum_prefix
from motionile.modules.skills.exceptions import SkillEmbeddingDimensionsError
from motionile.modules.skills.models import EMBEDDING_DIMENSIONS
from motionile.modules.skills.repository import (
    NewSkill,
    NewSkillVersion,
    SkillState,
    SkillStore,
    SqlSkillRepository,
    StoreFactory,
    Transaction,
)

SEED_USER_ID: Final = UUID(int=0)
SEED_STAGE: Final = "seed"


class Outcome(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


@dataclass(frozen=True, slots=True)
class SeedReport:
    created: int
    updated: int
    unchanged: int
    embedded: int


@dataclass(frozen=True, slots=True)
class Applied:
    outcome: Outcome
    embedded: bool


class SkillSeeder:
    def __init__(
        self,
        transaction: Transaction,
        embedder: Embedder,
        clock: Clock,
        store_factory: StoreFactory = SqlSkillRepository,
    ) -> None:
        self._transaction = transaction
        self._embedder = embedder
        self._clock = clock
        self._store_factory = store_factory

    async def sync(self, library: Sequence[SkillDocument]) -> SeedReport:
        if self._embedder.dimensions != EMBEDDING_DIMENSIONS:
            raise SkillEmbeddingDimensionsError
        vectors = await self._embed_missing(library)
        applied: list[Applied] = []
        for document in library:
            async with self._transaction() as session:
                applied.append(await self._apply(session, self._store_factory(session), document, vectors))
        return SeedReport(
            created=sum(item.outcome is Outcome.CREATED for item in applied),
            updated=sum(item.outcome is Outcome.UPDATED for item in applied),
            unchanged=sum(item.outcome is Outcome.UNCHANGED for item in applied),
            embedded=sum(item.embedded for item in applied),
        )

    def _context(self) -> CallContext:
        return CallContext(user_id=SEED_USER_ID, job_id=None, stage=SEED_STAGE, call_key=f"skills.seed:{new_id()}")

    async def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embedder.embed(texts, self._context())

    def _needs_embedding(self, document: SkillDocument, state: SkillState | None) -> bool:
        return state is None or state.checksum != document.checksum or state.embedding_model != self._embedder.model

    async def _embed_missing(self, library: Sequence[SkillDocument]) -> Mapping[str, list[float]]:
        async with self._transaction() as session:
            states = await self._store_factory(session).states()
        pending = [document for document in library if self._needs_embedding(document, states.get(document.slug))]
        if not pending:
            return {}
        embedded = await self._embed([document.description for document in pending])
        return {document.slug: vector for document, vector in zip(pending, embedded, strict=True)}

    async def _apply(
        self,
        session: AsyncSession,
        store: SkillStore,
        document: SkillDocument,
        vectors: Mapping[str, list[float]],
    ) -> Applied:
        await store.lock(document.slug)
        state = await store.state_of(document.slug)
        if state is not None and state.checksum == document.checksum and state.version_id is not None:
            embedded = await self._ensure_embedding(store, state, state.version_id, document, vectors)
            return Applied(Outcome.UNCHANGED, embedded)
        skill_id, number, outcome = await self._skill_for(store, document, state)
        version_id = await store.insert_version(
            NewSkillVersion(
                skill_id=skill_id,
                number=number,
                body=document.body,
                frontmatter=dict(document.frontmatter),
                checksum=document.checksum,
                scanned_at=self._clock.now(),
            )
        )
        await store.point_to_version(skill_id, version_id, document.name, document.description)
        await self._write_embedding(store, version_id, document, vectors)
        await self._audit(session, outcome, skill_id, document, number)
        return Applied(outcome, True)

    async def _skill_for(
        self, store: SkillStore, document: SkillDocument, state: SkillState | None
    ) -> tuple[UUID, int, Outcome]:
        if state is None:
            skill_id = await store.insert_skill(NewSkill(document.slug, document.name, document.description))
            return skill_id, 1, Outcome.CREATED
        return state.skill_id, await store.latest_number(state.skill_id) + 1, Outcome.UPDATED

    async def _ensure_embedding(
        self,
        store: SkillStore,
        state: SkillState,
        version_id: UUID,
        document: SkillDocument,
        vectors: Mapping[str, list[float]],
    ) -> bool:
        if state.embedding_model == self._embedder.model:
            return False
        await self._write_embedding(store, version_id, document, vectors)
        return True

    async def _write_embedding(
        self, store: SkillStore, version_id: UUID, document: SkillDocument, vectors: Mapping[str, list[float]]
    ) -> None:
        vector = vectors.get(document.slug)
        if vector is None:
            (vector,) = await self._embed([document.description])
        await store.upsert_embedding(version_id, vector, self._embedder.model)

    async def _audit(
        self, session: AsyncSession, outcome: Outcome, skill_id: UUID, document: SkillDocument, number: int
    ) -> None:
        action = SkillAction.CREATED if outcome is Outcome.CREATED else SkillAction.VERSION_ADDED
        await record_audit(
            session,
            AuditEvent(
                action=action.value,
                actor_type=ActorType.SYSTEM,
                target_type=AUDIT_TARGET,
                target_id=str(skill_id),
                metadata={"slug": document.slug, "version": number, "checksum": checksum_prefix(document.checksum)},
            ),
        )
