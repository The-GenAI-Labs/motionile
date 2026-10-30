from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

import pytest
from tests.fakes.skills_store import EPOCH, SkillWorld
from tests.unit.engine.ai.skills.support import library

from motionile.core.clock import FrozenClock
from motionile.engine.ai.llm.embeddings import FakeEmbedder
from motionile.engine.ai.llm.models import CallContext
from motionile.engine.ai.skills.loader import SkillDocument
from motionile.modules.audit import AuditContext, AuditEvent
from motionile.modules.skills import seed as seed_module
from motionile.modules.skills import service as service_module
from motionile.modules.skills.seed import SkillSeeder
from motionile.modules.skills.service import LibraryLoader, SkillsService

ADMIN = UUID("01939a5e-0000-7000-8000-0000000000a3")
CONTEXT = AuditContext()
LIBRARY_SIZE = 30


class CountingEmbedder(FakeEmbedder):
    def __init__(self, model: str = "fake-embedding", dimensions: int = 1536) -> None:
        super().__init__(dimensions=dimensions, model=model)
        self.texts: list[str] = []
        self.failure: Exception | None = None

    async def embed(self, texts: Sequence[str], context: CallContext) -> list[list[float]]:
        if self.failure is not None:
            raise self.failure
        self.texts.extend(texts)
        return await super().embed(texts, context)


@dataclass
class Harness:
    world: SkillWorld
    embedder: CountingEmbedder
    seeder: SkillSeeder
    service: SkillsService
    documents: list[SkillDocument]
    audit: list[AuditEvent] = field(default_factory=list[AuditEvent])

    def seeder_for(self, embedder: CountingEmbedder) -> SkillSeeder:
        return SkillSeeder(self.world.transaction, embedder, FrozenClock(EPOCH), self.world.store)


def make_harness(
    monkeypatch: pytest.MonkeyPatch,
    embedder: CountingEmbedder | None = None,
    loader: LibraryLoader | None = None,
) -> Harness:
    world = SkillWorld()
    resolved = embedder or CountingEmbedder()
    audit: list[AuditEvent] = []
    documents = list(library())

    async def record_audit(session: object, event: AuditEvent, context: AuditContext | None = None) -> None:
        del session, context
        audit.append(event)

    async def shipped() -> Sequence[SkillDocument]:
        return documents

    monkeypatch.setattr(seed_module, "record_audit", record_audit)
    monkeypatch.setattr(service_module, "record_audit", record_audit)
    seeder = SkillSeeder(world.transaction, resolved, FrozenClock(EPOCH), world.store)
    service = SkillsService(
        transaction=world.transaction,
        store_factory=world.store,
        seeder=seeder,
        embedding_model=resolved.model,
        library=loader or shipped,
    )
    return Harness(world, resolved, seeder, service, documents, audit)
