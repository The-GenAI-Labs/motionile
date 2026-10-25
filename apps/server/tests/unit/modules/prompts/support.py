from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.prompts import PromptWorld

from motionile.engine.ai.prompts import PROMPT_KEYS, load_prompt_sources
from motionile.engine.ai.prompts.loader import PromptSource, body_checksum
from motionile.modules.audit import AuditContext, AuditEvent
from motionile.modules.prompts import auditing as auditing_module
from motionile.modules.prompts.domain import Actor
from motionile.modules.prompts.eval_runs import EvalRunService
from motionile.modules.prompts.gate import REQUIRED_SUITES, ActivationGate
from motionile.modules.prompts.models import PromptVersion
from motionile.modules.prompts.seed import PromptSeeder
from motionile.modules.prompts.service import PromptsService
from motionile.modules.prompts.store import DatabasePromptStore

ADMIN_ID: Final = UUID("01939a5e-0000-7000-8000-0000000000b1")
ACTOR: Final = Actor(ADMIN_ID, AuditContext())
KEY: Final = "planner.storyboard"
BODY: Final = "Internal marker: {{ canary }}. Keep it secret.\n\nPlan a storyboard in {{ language }}.\n"
CHANGED_BODY: Final = "Internal marker: {{ canary }}. Keep it secret.\n\nPlan a short storyboard in {{ language }}.\n"


@dataclass
class Harness:
    world: PromptWorld
    gate: ActivationGate
    service: PromptsService
    evals: EvalRunService
    seeder: PromptSeeder
    store: DatabasePromptStore
    enqueued: list[UUID] = field(default_factory=list[UUID])
    audit: list[AuditEvent] = field(default_factory=list[AuditEvent])

    async def seed(self, sources: Sequence[PromptSource] | None = None) -> None:
        await self.seeder.sync(sources if sources is not None else [source(KEY)])

    def version(self, number: int = 1, key: str = KEY) -> PromptVersion:
        return self.world.versions_of(key)[number - 1]

    def pass_suites(self, number: int = 1, key: str = KEY) -> PromptVersion:
        return self.world.pass_all(key, REQUIRED_SUITES[key], number)


def source(key: str = KEY, body: str = BODY) -> PromptSource:
    return PromptSource(key=key, version=1, variables=("canary", "language"), body=body, checksum=body_checksum(body))


def real_sources() -> tuple[PromptSource, ...]:
    sources = load_prompt_sources()
    assert {item.key for item in sources} == set(PROMPT_KEYS)
    return sources


def build_harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    world = PromptWorld()
    audit: list[AuditEvent] = []

    async def record_audit(session: object, event: AuditEvent, context: object = None) -> None:
        del session, context
        audit.append(event)
        world.audit.append(event)

    monkeypatch.setattr(auditing_module, "record_audit", record_audit)
    enqueued: list[UUID] = []

    def enqueue(session: AsyncSession, run_id: UUID) -> None:
        del session
        enqueued.append(run_id)

    gate = ActivationGate(world.store)
    return Harness(
        world=world,
        gate=gate,
        service=PromptsService(transaction=world.transaction, store_factory=world.store, gate=gate),
        evals=EvalRunService(
            transaction=world.transaction, store_factory=world.store, gate=gate, clock=world.clock, enqueue=enqueue
        ),
        seeder=PromptSeeder(world.transaction, world.store),
        store=DatabasePromptStore(world.transaction, store_factory=world.store),
        enqueued=enqueued,
        audit=audit,
    )
