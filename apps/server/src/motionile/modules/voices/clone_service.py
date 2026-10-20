import hashlib
from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import Clock
from motionile.core.config import BillingSettings, VoicesSettings
from motionile.core.db import after_commit
from motionile.core.ids import new_id
from motionile.engine.audio.voice_clone import generate_consent_sentence
from motionile.modules.audit import ActorType, AuditContext, AuditEvent
from motionile.modules.audit import record as record_audit
from motionile.modules.credits import CreditsService, ReserveCommand
from motionile.modules.media import (
    AssetKind,
    AssetNotFoundError,
    AssetService,
    AssetSpec,
    consent_recording_key,
    voice_sample_key,
)
from motionile.modules.voices.clone import (
    MAX_SAMPLE_FILES,
    MS_PER_SECOND,
    WAV_CONTENT_TYPE,
    AttemptStore,
    AudioProcessor,
    CloneAttempt,
    CloneSubmission,
    StoredAudio,
    consent_limits,
    sample_limits,
)
from motionile.modules.voices.exceptions import (
    CloneAttemptNotFoundError,
    CloneSampleNotFoundError,
    ConsentRecordingMissingError,
    ConsentStatementOutdatedError,
    SamplesTooLongError,
    SamplesTooShortError,
    TooManySamplesError,
    VoiceQuotaExceededError,
)
from motionile.modules.voices.ports import Transaction
from motionile.modules.voices.repository import NewClonedVoice, StoreFactory, VoiceStore
from motionile.modules.voices.runtime import RuntimeSettings
from motionile.modules.voices.schemas import (
    CloneAttemptView,
    CloneLimitsView,
    CloneSampleView,
    CloneStartView,
    CloneSubmitRequest,
    ConsentRecordingView,
    VoiceView,
)
from motionile.modules.voices.views import voice_view

type EnqueueClone = Callable[[AsyncSession, UUID, UUID | None], None]

RESERVATION_REF_TYPE = "voice_clone"
AUDIT_TARGET = "voice"


def reservation_key(voice_id: UUID) -> str:
    return f"voice-clone:{voice_id}:reserve"


class CloneService:
    def __init__(  # noqa: PLR0913
        self,
        *,
        transaction: Transaction,
        store_factory: StoreFactory,
        assets: AssetService,
        attempts: AttemptStore,
        processor: AudioProcessor,
        settings: VoicesSettings,
        billing: BillingSettings,
        clock: Clock,
        credit_service: CreditsService,
        runtime: RuntimeSettings,
        enqueue: EnqueueClone,
        provider: str,
    ) -> None:
        self._transaction = transaction
        self._store_factory = store_factory
        self._assets = assets
        self._attempts = attempts
        self._processor = processor
        self._settings = settings
        self._billing = billing
        self._clock = clock
        self._credits = credit_service
        self._runtime = runtime
        self._enqueue = enqueue
        self._provider = provider

    async def start(self, user_id: UUID, statement_version: str, context: AuditContext) -> CloneStartView:
        async with self._transaction() as session:
            if statement_version != await self._runtime.consent_statement_version(session):
                raise ConsentStatementOutdatedError
            statement = await self._runtime.consent_statement(session)
            await self._require_quota(session, self._store_factory(session), user_id)
        now = self._clock.now()
        attempt = CloneAttempt(
            attempt_id=new_id(),
            user_id=user_id,
            voice_id=new_id(),
            sentence=generate_consent_sentence(),
            statement_version=statement_version,
            statement_sha256=hashlib.sha256(statement.encode()).hexdigest(),
            accepted_at=now,
            ip=str(context.ip) if context.ip is not None else None,
            user_agent=context.user_agent,
            expires_at=now + timedelta(seconds=self._settings.attempt_ttl_seconds),
        )
        await self._attempts.create(attempt)
        return CloneStartView(
            attempt_id=attempt.attempt_id,
            voice_id=attempt.voice_id,
            consent_sentence=attempt.sentence,
            statement_text=statement,
            statement_version=statement_version,
            expires_at=attempt.expires_at,
            limits=self._limits(),
        )

    async def state(self, user_id: UUID, attempt_id: UUID) -> CloneAttemptView:
        return self._view(await self._attempt(user_id, attempt_id))

    async def replace_consent_recording(self, user_id: UUID, attempt_id: UUID, data: bytes) -> CloneAttemptView:
        await self._attempt(user_id, attempt_id)
        processed = await self._processor.process(data, consent_limits(self._settings))
        async with self._attempts.locked(attempt_id):
            attempt = await self._attempt(user_id, attempt_id)
            if attempt.consent is not None:
                await self._discard(user_id, attempt.consent.asset_id)
                attempt = attempt.model_copy(update={"consent": None})
                await self._save(attempt)
            stored = await self._store(
                user_id, consent_recording_key(user_id, attempt.voice_id), processed.data, processed.duration_ms
            )
            attempt = attempt.model_copy(update={"consent": stored})
            await self._save(attempt)
        return self._view(attempt)

    async def add_sample(self, user_id: UUID, attempt_id: UUID, data: bytes) -> CloneAttemptView:
        await self._attempt(user_id, attempt_id)
        processed = await self._processor.process(data, sample_limits(self._settings))
        async with self._attempts.locked(attempt_id):
            attempt = await self._attempt(user_id, attempt_id)
            if len(attempt.samples) >= MAX_SAMPLE_FILES:
                raise TooManySamplesError
            if attempt.total_sample_ms + processed.duration_ms > self._max_total_ms:
                raise SamplesTooLongError
            index = attempt.next_index
            stored = await self._store(
                user_id, voice_sample_key(user_id, attempt.voice_id, index), processed.data, processed.duration_ms
            )
            attempt = attempt.model_copy(
                update={
                    "samples": [*attempt.samples, stored.model_copy(update={"index": index})],
                    "next_index": index + 1,
                }
            )
            await self._save(attempt)
        return self._view(attempt)

    async def remove_sample(self, user_id: UUID, attempt_id: UUID, sample_id: UUID) -> CloneAttemptView:
        await self._attempt(user_id, attempt_id)
        async with self._attempts.locked(attempt_id):
            attempt = await self._attempt(user_id, attempt_id)
            if not any(sample.asset_id == sample_id for sample in attempt.samples):
                raise CloneSampleNotFoundError
            await self._discard(user_id, sample_id)
            attempt = attempt.model_copy(
                update={"samples": [sample for sample in attempt.samples if sample.asset_id != sample_id]}
            )
            await self._save(attempt)
        return self._view(attempt)

    async def submit(
        self, user_id: UUID, attempt_id: UUID, request: CloneSubmitRequest, context: AuditContext
    ) -> VoiceView:
        await self._attempt(user_id, attempt_id)
        async with self._attempts.locked(attempt_id):
            attempt = await self._attempt(user_id, attempt_id)
            self._require_complete(attempt)
            return await self._submit(user_id, attempt, request, context)

    async def _submit(
        self, user_id: UUID, attempt: CloneAttempt, request: CloneSubmitRequest, context: AuditContext
    ) -> VoiceView:
        consent = attempt.consent
        if consent is None:
            raise ConsentRecordingMissingError
        async with self._transaction() as session:
            store = self._store_factory(session)
            await store.lock_quota(user_id)
            await self._require_quota(session, store, user_id)
            cost = await self._runtime.clone_credit_cost(session)
            reservation_id: UUID | None = None
            if cost > 0:
                reservation = await self._credits.reserve(
                    session,
                    ReserveCommand(
                        user_id=user_id,
                        amount=cost,
                        ref_type=RESERVATION_REF_TYPE,
                        ref_id=attempt.voice_id,
                        key=reservation_key(attempt.voice_id),
                        ttl=timedelta(seconds=self._billing.reservation_ttl_seconds),
                    ),
                )
                reservation_id = reservation.id
            voice = await store.insert_cloned(
                NewClonedVoice(attempt.voice_id, user_id, self._provider, request.name, request.language)
            )
            await self._attempts.put_submission(
                CloneSubmission(
                    voice_id=attempt.voice_id,
                    user_id=user_id,
                    sentence=attempt.sentence,
                    statement_version=attempt.statement_version,
                    statement_sha256=attempt.statement_sha256,
                    accepted_at=attempt.accepted_at,
                    ip=attempt.ip,
                    user_agent=attempt.user_agent,
                    consent_asset_id=consent.asset_id,
                    sample_asset_ids=[sample.asset_id for sample in attempt.samples],
                    sample_total_ms=attempt.total_sample_ms,
                    credits_reserved=cost,
                )
            )
            await record_audit(
                session,
                AuditEvent(
                    action="voices.clone_submitted",
                    actor_type=ActorType.USER,
                    actor_user_id=user_id,
                    target_type=AUDIT_TARGET,
                    target_id=str(voice.id),
                    metadata={"samples": len(attempt.samples), "credits": cost},
                ),
                context,
            )
            self._enqueue(session, voice.id, reservation_id)
            after_commit(session, lambda: self._attempts.delete(attempt.attempt_id))
            return voice_view(voice)

    def _require_complete(self, attempt: CloneAttempt) -> None:
        if attempt.consent is None:
            raise ConsentRecordingMissingError
        total = attempt.total_sample_ms
        if not attempt.samples or total < self._settings.sample_min_total_seconds * MS_PER_SECOND:
            raise SamplesTooShortError
        if total > self._max_total_ms:
            raise SamplesTooLongError

    async def _require_quota(self, session: AsyncSession, store: VoiceStore, user_id: UUID) -> None:
        limit = await self._runtime.max_cloned_per_user(session)
        if await store.count_cloned(user_id) >= limit:
            raise VoiceQuotaExceededError

    async def _attempt(self, user_id: UUID, attempt_id: UUID) -> CloneAttempt:
        attempt = await self._attempts.get(attempt_id, user_id)
        if attempt is None:
            raise CloneAttemptNotFoundError
        return attempt

    async def _save(self, attempt: CloneAttempt) -> None:
        if not await self._attempts.save(attempt):
            raise CloneAttemptNotFoundError

    async def _store(self, user_id: UUID, key: str, data: bytes, duration_ms: int) -> StoredAudio:
        async with self._transaction() as session:
            view = await self._assets.store_bytes(
                session,
                data,
                AssetSpec(
                    key=key,
                    kind=AssetKind.VOICE_SAMPLE,
                    content_type=WAV_CONTENT_TYPE,
                    owner_user_id=user_id,
                    duration_ms=duration_ms,
                ),
            )
        return StoredAudio(asset_id=view.id, duration_ms=duration_ms, size_bytes=view.size_bytes)

    async def _discard(self, user_id: UUID, asset_id: UUID) -> None:
        async with self._transaction() as session:
            try:
                await self._assets.delete(session, user_id, asset_id)
            except AssetNotFoundError:
                return

    @property
    def _max_total_ms(self) -> int:
        return self._settings.sample_max_total_seconds * MS_PER_SECOND

    def _limits(self) -> CloneLimitsView:
        return CloneLimitsView(
            sample_min_total_seconds=self._settings.sample_min_total_seconds,
            sample_max_total_seconds=self._settings.sample_max_total_seconds,
            sample_max_bytes=self._settings.sample_max_bytes,
            consent_min_seconds=self._settings.consent_min_seconds,
            consent_max_seconds=self._settings.consent_max_seconds,
            max_sample_files=MAX_SAMPLE_FILES,
        )

    def _view(self, attempt: CloneAttempt) -> CloneAttemptView:
        consent = attempt.consent
        return CloneAttemptView(
            attempt_id=attempt.attempt_id,
            voice_id=attempt.voice_id,
            consent_sentence=attempt.sentence,
            statement_version=attempt.statement_version,
            expires_at=attempt.expires_at,
            consent_recording=(
                ConsentRecordingView(duration_ms=consent.duration_ms, size_bytes=consent.size_bytes)
                if consent is not None
                else None
            ),
            samples=[
                CloneSampleView(id=sample.asset_id, duration_ms=sample.duration_ms, size_bytes=sample.size_bytes)
                for sample in attempt.samples
            ],
            total_sample_ms=attempt.total_sample_ms,
            limits=self._limits(),
        )
