from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.credits import FakeAudit, FakeCreditsStore
from tests.fakes.generation import (
    FakeCheckpoints,
    FakeEditGuard,
    FakeMusic,
    FakePreferences,
    FakeRenders,
    FakeSettingsReader,
    FakeSkills,
    FakeTopics,
    FakeVoices,
    GenerationWorld,
    RecordingAudit,
    RecordingDispatch,
)
from tests.fakes.settings import make_settings

from motionile.core.clock import FrozenClock
from motionile.core.events import EventBus
from motionile.core.ids import new_id
from motionile.engine.ai.job_options import JobOptions
from motionile.engine.ai.storyboard import Storyboard
from motionile.modules.credits import CreditRef, CreditsService, GrantCommand
from motionile.modules.generation.models import Job
from motionile.modules.generation.models import Storyboard as StoryboardRow
from motionile.modules.generation.options import OptionResolver
from motionile.modules.generation.ports import JobDispatch
from motionile.modules.generation.runtime_settings import RuntimeSettings
from motionile.modules.generation.schemas import JobCreateRequest, JobOptionsRequest
from motionile.modules.generation.service import GenerationDeps, GenerationService

START = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
SCENE_COUNT = 4
SCENE_MS = 15_000
WORDS_PER_SCENE = 36


def storyboard_content(**overrides: Any) -> dict[str, Any]:
    scenes = [
        {
            "id": f"scene-{index}",
            "position": index,
            "goal": f"Explain part {index}",
            "narration": " ".join(f"word{index}x{word}" for word in range(WORDS_PER_SCENE)),
            "visualBrief": "A diagram building step by step",
            "layoutNotes": {"16:9": "Centered diagram"},
            "visualSkills": [],
            "keyTerms": ["packet"],
            "onScreenText": ["Packets"],
            "targetDurationMs": SCENE_MS,
        }
        for index in range(SCENE_COUNT)
    ]
    return {
        "version": 1,
        "title": "How TCP works",
        "summary": "A short tour of TCP.",
        "audienceLevel": "beginner",
        "language": "en",
        "targetDurationMs": SCENE_COUNT * SCENE_MS,
        "aspects": ["16:9"],
        "styleSkill": "minimal-dark",
        "scenes": scenes,
        **overrides,
    }


def valid_storyboard() -> Storyboard:
    return Storyboard.model_validate(storyboard_content())


class Harness:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.clock = FrozenClock(START)
        self.world = GenerationWorld()
        self.credit_store = FakeCreditsStore(self.clock)
        self.credit_audit = FakeAudit()
        self.credits = CreditsService(
            self.clock, make_settings().billing, store_factory=self.credit_store, audit=self.credit_audit
        )
        self.reader = FakeSettingsReader()
        self.runtime = RuntimeSettings(self.reader)
        self.preferences = FakePreferences()
        self.skills = FakeSkills()
        self.voices = FakeVoices()
        self.music = FakeMusic()
        self.topics = FakeTopics()
        self.guard = FakeEditGuard()
        self.renders = FakeRenders()
        self.checkpoints = FakeCheckpoints()
        self.dispatch = RecordingDispatch()
        self.audit = RecordingAudit()
        self.events = EventBus()
        self.user_id = new_id()
        self.other_id = new_id()
        self.service = GenerationService(
            GenerationDeps(
                credits=self.credits,
                settings=self.runtime,
                options=OptionResolver(self.runtime, self.preferences, self.skills, self.voices, self.music),
                topics=self.topics,
                edit_guard=self.guard,
                renders=self.renders,
                checkpoints=self.checkpoints,
                clock=self.clock,
                events=self.events,
                dispatch=JobDispatch(run=self.dispatch.run, resume=self.dispatch.resume),
                store_factory=self.world.factory,
                audit=self.audit,
            )
        )
        self.counter = 0
        self.open_transactions = 0
        self.guard.open_transactions = lambda: self.open_transactions

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession]:
        self.open_transactions += 1
        try:
            yield self.session
        finally:
            self.open_transactions -= 1

    def key(self) -> str:
        self.counter += 1
        return f"key-{self.counter}"

    async def fund(self, amount: int, user_id: UUID | None = None) -> None:
        await self.credits.grant(
            self.session,
            GrantCommand(
                user_id=user_id or self.user_id,
                amount=amount,
                source="purchase",
                key=f"grant-{new_id()}",
                ref=CreditRef("payment", new_id()),
            ),
        )

    def request(self, **options: Any) -> JobCreateRequest:
        return JobCreateRequest(query="How does TCP work?", options=JobOptionsRequest(duration_seconds=60, **options))

    def wallet(self, user_id: UUID | None = None) -> tuple[int, int]:
        record = self.credit_store.wallets[user_id or self.user_id]
        return record.balance, record.reserved

    def waiting_job(self, *, approved: bool = False) -> tuple[Job, StoryboardRow]:
        job = self.world.add_job(self.user_id, status="awaiting_approval", started_at=START)
        row = self.world.add_storyboard(job, storyboard_content())
        if approved:
            row.approved_at = START
            row.approved_by = self.user_id
        return job, row

    def options_of(self, job: Job) -> JobOptions:
        return JobOptions.model_validate(job.options)
