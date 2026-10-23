from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.media import World

from motionile.core.ids import new_id
from motionile.core.pagination import Cursor
from motionile.core.redis import RedisKeyBuilder
from motionile.engine.audio.audio_validation import AudioRejectedError, AudioUploadLimits
from motionile.modules.media import Asset
from motionile.modules.voices.clone import ProcessedAudio, rejection_for
from motionile.modules.voices.domain import VoiceKind, VoiceStatus
from motionile.modules.voices.models import Voice, VoiceConsent
from motionile.modules.voices.repository import NewBuiltinVoice, NewClonedVoice, NewConsent, VoiceFilter

EPOCH = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
STATEMENT = "I confirm this is my own voice and I agree to the terms. " * 2
VERSION = "2026-10-19"


@dataclass
class VoiceWorld:
    media: World = field(default_factory=World)
    voices: dict[UUID, Voice] = field(default_factory=dict[UUID, Voice])
    consents: list[VoiceConsent] = field(default_factory=list[VoiceConsent])
    tick: int = 0

    def store(self, session: AsyncSession) -> "InMemoryVoiceStore":
        del session
        return InMemoryVoiceStore(self)

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession]:
        saved = {
            voice_id: (voice.status, voice.failure_code, voice.provider_voice_id, voice.preview_asset_id)
            for voice_id, voice in self.voices.items()
        }
        consents = list(self.consents)
        referenced = set(self.media.referenced)
        try:
            async with self.media.transaction() as session:
                yield session
        except BaseException:
            for voice_id, (status, failure_code, provider_voice_id, preview_asset_id) in saved.items():
                voice = self.voices[voice_id]
                voice.status = status
                voice.failure_code = failure_code
                voice.provider_voice_id = provider_voice_id
                voice.preview_asset_id = preview_asset_id
            self.consents = consents
            self.media.referenced = referenced
            raise

    def stamp(self) -> datetime:
        self.tick += 1
        return EPOCH + timedelta(seconds=self.tick)

    def add_voice(self, **overrides: Any) -> Voice:
        stamp = self.stamp()
        values: dict[str, Any] = {
            "id": new_id(),
            "owner_user_id": None,
            "provider": "fake",
            "provider_voice_id": "fake-voice-aria",
            "name": "Aria",
            "kind": "builtin",
            "language": "en",
            "status": "ready",
            "failure_code": None,
            "preview_asset_id": None,
            "labels": {},
            "created_at": stamp,
            "updated_at": stamp,
            **overrides,
        }
        voice = Voice(**values)
        self.voices[voice.id] = voice
        return voice


class InMemoryVoiceStore:
    def __init__(self, world: VoiceWorld) -> None:
        self._world = world

    async def get(self, voice_id: UUID) -> Voice | None:
        return self._world.voices.get(voice_id)

    def _visible(self, user_id: UUID, voice: Voice) -> bool:
        public = voice.kind == VoiceKind.BUILTIN.value and voice.status == VoiceStatus.READY.value
        return public or voice.owner_user_id == user_id

    async def get_visible(self, user_id: UUID, voice_id: UUID) -> Voice | None:
        voice = self._world.voices.get(voice_id)
        return voice if voice is not None and self._visible(user_id, voice) else None

    async def get_owned(self, user_id: UUID, voice_id: UUID) -> Voice | None:
        voice = self._world.voices.get(voice_id)
        if voice is not None and voice.owner_user_id == user_id and voice.kind == VoiceKind.CLONED.value:
            return voice
        return None

    async def get_builtin(self, voice_id: UUID) -> Voice | None:
        voice = self._world.voices.get(voice_id)
        return voice if voice is not None and voice.kind == VoiceKind.BUILTIN.value else None

    @staticmethod
    def _page(rows: list[Voice], voice_filter: VoiceFilter, cursor: Cursor | None, limit: int) -> list[Voice]:
        matching = [
            row
            for row in rows
            if (voice_filter.language is None or row.language.split("-")[0] == voice_filter.language)
            and (voice_filter.kind is None or row.kind == voice_filter.kind)
            and (voice_filter.status is None or row.status == voice_filter.status)
            and (cursor is None or (row.created_at, row.id) < (cursor.created_at, cursor.id))
        ]
        matching.sort(key=lambda row: (row.created_at, row.id), reverse=True)
        return matching[: limit + 1]

    async def page_visible(
        self, user_id: UUID, voice_filter: VoiceFilter, cursor: Cursor | None, limit: int
    ) -> list[Voice]:
        rows = [row for row in self._world.voices.values() if self._visible(user_id, row)]
        return self._page(rows, voice_filter, cursor, limit)

    async def page_builtin(self, voice_filter: VoiceFilter, cursor: Cursor | None, limit: int) -> list[Voice]:
        rows = [row for row in self._world.voices.values() if row.kind == VoiceKind.BUILTIN.value]
        return self._page(rows, voice_filter, cursor, limit)

    async def count_cloned(self, user_id: UUID) -> int:
        return sum(
            1
            for row in self._world.voices.values()
            if row.owner_user_id == user_id and row.status != VoiceStatus.FAILED.value
        )

    async def lock_quota(self, user_id: UUID) -> None:
        del user_id

    async def insert_cloned(self, row: NewClonedVoice) -> Voice:
        return self._world.add_voice(
            id=row.id,
            owner_user_id=row.owner_user_id,
            provider=row.provider,
            provider_voice_id=None,
            name=row.name,
            kind="cloned",
            language=row.language,
            status="pending",
        )

    async def insert_builtin_if_absent(self, rows: Sequence[NewBuiltinVoice]) -> int:
        added = 0
        for row in rows:
            if any(
                voice.provider == row.provider and voice.provider_voice_id == row.provider_voice_id
                for voice in self._world.voices.values()
            ):
                continue
            self._world.add_voice(
                provider=row.provider,
                provider_voice_id=row.provider_voice_id,
                name=row.name,
                language=row.language,
                status="disabled",
                labels=dict(row.labels),
            )
            added += 1
        return added

    async def set_provider_voice_id(self, voice_id: UUID, provider_voice_id: str) -> bool:
        voice = self._world.voices.get(voice_id)
        if voice is None or voice.status != "pending" or voice.provider_voice_id is not None:
            return False
        voice.provider_voice_id = provider_voice_id
        return True

    async def mark_ready(self, voice_id: UUID, preview_asset_id: UUID | None) -> bool:
        voice = self._world.voices.get(voice_id)
        if voice is None or voice.status != "pending" or voice.provider_voice_id is None:
            return False
        voice.status = "ready"
        voice.failure_code = None
        voice.preview_asset_id = preview_asset_id
        return True

    async def mark_failed(self, voice_id: UUID, failure_code: str) -> bool:
        voice = self._world.voices.get(voice_id)
        if voice is None or voice.status != "pending":
            return False
        voice.status = "failed"
        voice.failure_code = failure_code
        voice.provider_voice_id = None
        return True

    async def update_builtin(self, voice_id: UUID, values: Mapping[str, Any]) -> Voice | None:
        voice = await self.get_builtin(voice_id)
        if voice is None:
            return None
        for name, value in values.items():
            setattr(voice, name, value)
        return voice

    async def set_preview(self, voice_id: UUID, asset_id: UUID | None) -> bool:
        voice = self._world.voices.get(voice_id)
        if voice is None:
            return False
        voice.preview_asset_id = asset_id
        return True

    async def delete(self, voice_id: UUID, owner_user_id: UUID | None) -> bool:
        voice = self._world.voices.get(voice_id)
        if voice is None or voice.status == "pending" or voice.owner_user_id != owner_user_id:
            return False
        del self._world.voices[voice_id]
        for consent in self._world.consents:
            if consent.voice_id == voice_id:
                consent.voice_id = None
        return True

    async def insert_consent(self, row: NewConsent) -> VoiceConsent:
        consent = VoiceConsent(
            id=new_id(),
            voice_id=row.voice_id,
            voice_reference=row.voice_id,
            user_id=row.user_id,
            statement_version=row.statement_version,
            statement_sha256=row.statement_sha256,
            accepted_at=row.accepted_at,
            ip=row.ip,
            user_agent=row.user_agent,
            consent_asset_id=row.consent_asset_id,
            challenge_sentence=row.challenge_sentence,
            transcript=row.transcript,
            match_percent=row.match_percent,
            sample_count=row.sample_count,
            sample_total_ms=row.sample_total_ms,
            created_at=EPOCH,
            updated_at=EPOCH,
        )
        self._world.consents.append(consent)
        self._world.media.referenced.add(row.consent_asset_id)
        return consent

    async def sample_assets(self, user_id: UUID, voice_id: UUID) -> list[Asset]:
        prefix = f"voice/u/{user_id}/{voice_id}/"
        consent_assets = {c.consent_asset_id for c in self._world.consents if c.voice_reference == voice_id}
        return [
            asset
            for asset in self._world.media.assets.values()
            if asset.owner_user_id == user_id
            and asset.storage_key.startswith(prefix)
            and asset.id not in consent_assets
        ]

    async def cloned_of(self, user_id: UUID) -> list[Voice]:
        return [v for v in self._world.voices.values() if v.owner_user_id == user_id and v.kind == "cloned"]

    async def consents_of(self, user_id: UUID) -> list[VoiceConsent]:
        return [c for c in self._world.consents if c.user_id == user_id]

    async def stalled_pending(self, before: datetime, limit: int) -> list[Voice]:
        rows = [v for v in self._world.voices.values() if v.status == "pending" and v.created_at < before]
        return rows[:limit]

    async def abandoned_sample_assets(self, before: datetime, limit: int) -> list[Asset]:
        known = {str(voice_id) for voice_id in self._world.voices}
        known |= {str(consent.voice_reference) for consent in self._world.consents}
        rows = [
            asset
            for asset in self._world.media.assets.values()
            if asset.kind == "voice_sample"
            and asset.owner_user_id is not None
            and asset.created_at < before
            and asset.storage_key.split("/")[3] not in known
        ]
        return rows[:limit]


class FakeKeyValue:
    def __init__(self) -> None:
        self.keys = RedisKeyBuilder("test")
        self.values: dict[str, bytes] = {}
        self.ttls: dict[str, timedelta] = {}

    async def set(self, key: str, value: bytes | str, *, ttl: timedelta) -> None:
        assert ttl > timedelta(0)
        self.values[key] = value.encode() if isinstance(value, str) else value
        self.ttls[key] = ttl

    async def set_if_absent(self, key: str, value: bytes | str, *, ttl: timedelta) -> bool:
        if key in self.values:
            return False
        await self.set(key, value, ttl=ttl)
        return True

    async def get(self, key: str) -> bytes | None:
        return self.values.get(key)

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)
        self.ttls.pop(key, None)


@dataclass
class StaticRuntime:
    max_cloned: int = 3
    cost: int = 0
    statement: str = STATEMENT
    version: str = VERSION

    async def max_cloned_per_user(self, session: AsyncSession) -> int:
        del session
        return self.max_cloned

    async def clone_credit_cost(self, session: AsyncSession) -> int:
        del session
        return self.cost

    async def consent_statement(self, session: AsyncSession) -> str:
        del session
        return self.statement

    async def consent_statement_version(self, session: AsyncSession) -> str:
        del session
        return self.version


@dataclass
class ScriptedProcessor:
    seconds: float = 40.0
    rejection: AudioRejectedError | None = None
    received: list[tuple[bytes, AudioUploadLimits]] = field(default_factory=list[tuple[bytes, AudioUploadLimits]])

    async def process(self, data: bytes, limits: AudioUploadLimits) -> ProcessedAudio:
        self.received.append((data, limits))
        if self.rejection is not None:
            raise rejection_for(self.rejection)
        return ProcessedAudio(b"wav:" + data, round(self.seconds * 1000))
