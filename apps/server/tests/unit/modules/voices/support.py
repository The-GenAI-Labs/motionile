from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.credits import FakeAudit, FakeCreditsStore
from tests.fakes.settings import make_settings
from tests.fakes.storage import InMemoryStorage
from tests.fakes.voices import EPOCH, FakeKeyValue, ScriptedProcessor, StaticRuntime, VoiceWorld

from motionile.core.clock import FrozenClock
from motionile.core.config import Settings
from motionile.core.ids import new_id
from motionile.engine.audio.providers.base import TTSProvider
from motionile.engine.audio.providers.fake import FakeTranscriber, FakeTranscriptMode, FakeTTSProvider, FakeVoiceService
from motionile.modules.audit import AuditContext, AuditEvent
from motionile.modules.credits import CreditRef, CreditsService, GrantCommand
from motionile.modules.media import AssetService, SpeechService
from motionile.modules.media import speech_cache as speech_cache_module
from motionile.modules.media.speech_cache import SqlSynthesisCache
from motionile.modules.voices import clone_service as clone_service_module
from motionile.modules.voices import service as service_module
from motionile.modules.voices.clone import AttemptStore
from motionile.modules.voices.clone_service import CloneService
from motionile.modules.voices.preview import PreviewGenerator
from motionile.modules.voices.runner import CloneRunner
from motionile.modules.voices.schemas import CloneSubmitRequest
from motionile.modules.voices.service import VoicesService

USER = UUID("01939a5e-0000-7000-8000-0000000000a1")
OTHER = UUID("01939a5e-0000-7000-8000-0000000000a2")
ADMIN = UUID("01939a5e-0000-7000-8000-0000000000a3")
CONTEXT = AuditContext()
SUBMIT_REQUEST = CloneSubmitRequest(name="My voice", language="en")


@dataclass
class CatalogSwitch:
    failure: Exception | None = None


@dataclass
class Harness:
    world: VoiceWorld
    storage: InMemoryStorage
    clock: FrozenClock
    settings: Settings
    values: FakeKeyValue
    runtime: StaticRuntime
    processor: ScriptedProcessor
    provider: FakeVoiceService
    tts: FakeTTSProvider
    transcriber: FakeTranscriber
    credits_store: FakeCreditsStore
    wallet_service: CreditsService
    assets: AssetService
    speech: SpeechService
    attempts: AttemptStore
    clone: CloneService
    runner: CloneRunner
    service: VoicesService
    switch: CatalogSwitch
    enqueued: list[tuple[UUID, UUID | None]] = field(default_factory=list[tuple[UUID, UUID | None]])
    audit: list[AuditEvent] = field(default_factory=list[AuditEvent])

    async def fund(self, user_id: UUID, amount: int) -> None:
        session = AsyncSession()
        await self.wallet_service.grant(
            session,
            GrantCommand(
                user_id=user_id,
                amount=amount,
                source="purchase",
                key=f"grant:{new_id()}",
                expires_at=None,
                ref=CreditRef("payment", new_id()),
            ),
        )

    async def prepared_attempt(self, user_id: UUID = USER, *, samples: int = 1) -> UUID:
        started = await self.clone.start(user_id, self.runtime.version, CONTEXT)
        await self.clone.replace_consent_recording(user_id, started.attempt_id, b"consent")
        for index in range(samples):
            await self.clone.add_sample(user_id, started.attempt_id, f"sample-{index}".encode())
        return started.attempt_id


def build_harness(monkeypatch: pytest.MonkeyPatch, *, seconds: float = 40.0) -> Harness:
    world = VoiceWorld()
    storage = InMemoryStorage()
    clock = FrozenClock(EPOCH)
    settings = make_settings()
    values = FakeKeyValue()
    runtime = StaticRuntime()
    processor = ScriptedProcessor(seconds=seconds)
    provider = FakeVoiceService()
    tts = FakeTTSProvider()
    transcriber = FakeTranscriber()
    credits_store = FakeCreditsStore(clock)
    wallet_service = CreditsService(clock, settings.billing, store_factory=credits_store, audit=FakeAudit())
    assets = AssetService(storage, world.media.asset_store)
    cache = SqlSynthesisCache(world.media.transaction, assets, clock, world.media.tts_store)
    audit: list[AuditEvent] = []

    async def record_usage(session: object, entry: object) -> None:
        del session, entry

    async def record_audit(session: object, event: AuditEvent, context: AuditContext | None = None) -> None:
        del session, context
        audit.append(event)

    monkeypatch.setattr(speech_cache_module, "record_usage", record_usage)
    monkeypatch.setattr(clone_service_module, "record_audit", record_audit)
    monkeypatch.setattr(service_module, "record_audit", record_audit)

    def providers(name: str | None) -> TTSProvider:
        del name
        return tts

    speech = SpeechService(world.media.transaction, cache, settings, providers)
    previews = PreviewGenerator(world.media.transaction, assets, speech, world.store)
    attempts = AttemptStore(values, clock)
    enqueued: list[tuple[UUID, UUID | None]] = []

    def enqueue(session: AsyncSession, voice_id: UUID, reservation_id: UUID | None) -> None:
        del session
        enqueued.append((voice_id, reservation_id))

    clone = CloneService(
        transaction=world.transaction,
        store_factory=world.store,
        assets=assets,
        attempts=attempts,
        processor=processor,
        settings=settings.voices,
        clock=clock,
        credit_service=wallet_service,
        runtime=runtime,
        enqueue=enqueue,
        provider="fake",
    )
    runner = CloneRunner(
        transaction=world.transaction,
        store_factory=world.store,
        assets=assets,
        attempts=attempts,
        speech=speech,
        previews=previews,
        transcriber=lambda: transcriber,
        cloner=lambda: provider,
        credit_service=wallet_service,
        settings=settings.voices,
        clock=clock,
    )
    switch = CatalogSwitch()

    def catalog() -> FakeVoiceService:
        if switch.failure is not None:
            raise switch.failure
        return provider

    service = VoicesService(
        transaction=world.transaction,
        store_factory=world.store,
        assets=assets,
        storage=storage,
        speech=speech,
        cloner=lambda: provider,
        catalog=catalog,
        previews=previews,
        clock=clock,
        preview_ttl=timedelta(seconds=600),
        catalog_provider="fake",
    )
    return Harness(
        world,
        storage,
        clock,
        settings,
        values,
        runtime,
        processor,
        provider,
        tts,
        transcriber,
        credits_store,
        wallet_service,
        assets,
        speech,
        attempts,
        clone,
        runner,
        service,
        switch,
        enqueued,
        audit,
    )


async def submitted(harness: Harness, *, cost: int = 0, matching: bool = True) -> tuple[UUID, UUID | None]:
    harness.runtime.cost = cost
    if cost:
        await harness.fund(USER, 100)
    attempt_id = await harness.prepared_attempt(samples=2)
    started = await harness.attempts.get(attempt_id, USER)
    assert started is not None
    harness.transcriber.mode = FakeTranscriptMode.FIXED if matching else FakeTranscriptMode.WRONG
    harness.transcriber.fixed_text = started.sentence
    voice = await harness.clone.submit(USER, attempt_id, SUBMIT_REQUEST, CONTEXT)
    [(voice_id, reservation_id)] = harness.enqueued
    assert voice_id == voice.id
    return voice_id, reservation_id
