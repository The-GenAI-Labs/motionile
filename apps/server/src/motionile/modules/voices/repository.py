from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import Select, Text, and_, cast, delete, exists, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.ids import new_id
from motionile.core.pagination import Cursor, keyset_page
from motionile.modules.media import Asset
from motionile.modules.voices.domain import VoiceKind, VoiceStatus
from motionile.modules.voices.models import Voice, VoiceConsent

FRESH_ROWS = {"populate_existing": True}
QUOTA_LOCK_NAMESPACE = "voices.quota"
KEY_VOICE_SEGMENT = 4


@dataclass(frozen=True, slots=True)
class VoiceFilter:
    language: str | None = None
    kind: str | None = None
    status: str | None = None


@dataclass(frozen=True, slots=True)
class NewClonedVoice:
    id: UUID
    owner_user_id: UUID
    provider: str
    name: str
    language: str


@dataclass(frozen=True, slots=True)
class NewBuiltinVoice:
    provider: str
    provider_voice_id: str
    name: str
    language: str
    labels: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class NewConsent:
    voice_id: UUID
    user_id: UUID
    statement_version: str
    statement_sha256: bytes
    accepted_at: datetime
    ip: str | None
    user_agent: str | None
    consent_asset_id: UUID
    challenge_sentence: str
    transcript: str
    match_percent: int
    sample_count: int
    sample_total_ms: int


type StoreFactory = Callable[[AsyncSession], VoiceStore]


class VoiceStore(Protocol):
    async def get(self, voice_id: UUID) -> Voice | None: ...

    async def get_visible(self, user_id: UUID, voice_id: UUID) -> Voice | None: ...

    async def get_owned(self, user_id: UUID, voice_id: UUID) -> Voice | None: ...

    async def get_builtin(self, voice_id: UUID) -> Voice | None: ...

    async def page_visible(
        self, user_id: UUID, voice_filter: VoiceFilter, cursor: Cursor | None, limit: int
    ) -> list[Voice]: ...

    async def page_builtin(self, voice_filter: VoiceFilter, cursor: Cursor | None, limit: int) -> list[Voice]: ...

    async def count_cloned(self, user_id: UUID) -> int: ...

    async def lock_quota(self, user_id: UUID) -> None: ...

    async def insert_cloned(self, row: NewClonedVoice) -> Voice: ...

    async def insert_builtin_if_absent(self, rows: Sequence[NewBuiltinVoice]) -> int: ...

    async def set_provider_voice_id(self, voice_id: UUID, provider_voice_id: str) -> bool: ...

    async def mark_ready(self, voice_id: UUID, preview_asset_id: UUID | None) -> bool: ...

    async def mark_failed(self, voice_id: UUID, failure_code: str) -> bool: ...

    async def update_builtin(self, voice_id: UUID, values: Mapping[str, Any]) -> Voice | None: ...

    async def set_preview(self, voice_id: UUID, asset_id: UUID | None) -> bool: ...

    async def delete(self, voice_id: UUID, owner_user_id: UUID | None) -> bool: ...

    async def insert_consent(self, row: NewConsent) -> VoiceConsent: ...

    async def sample_assets(self, user_id: UUID, voice_id: UUID) -> list[Asset]: ...

    async def cloned_of(self, user_id: UUID) -> list[Voice]: ...

    async def consents_of(self, user_id: UUID) -> list[VoiceConsent]: ...

    async def stalled_pending(self, before: datetime, limit: int) -> list[Voice]: ...

    async def abandoned_sample_assets(self, before: datetime, limit: int) -> list[Asset]: ...


def language_clause(language: str) -> Any:
    return or_(Voice.language == language, Voice.language.startswith(f"{language}-", autoescape=True))


def apply_filter(statement: Select[Any], voice_filter: VoiceFilter) -> Select[Any]:
    if voice_filter.language is not None:
        statement = statement.where(language_clause(voice_filter.language))
    if voice_filter.kind is not None:
        statement = statement.where(Voice.kind == voice_filter.kind)
    if voice_filter.status is not None:
        statement = statement.where(Voice.status == voice_filter.status)
    return statement


def visible_to(user_id: UUID) -> Any:
    return or_(
        and_(Voice.kind == VoiceKind.BUILTIN.value, Voice.status == VoiceStatus.READY.value),
        Voice.owner_user_id == user_id,
    )


class SqlVoiceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, voice_id: UUID) -> Voice | None:
        statement = select(Voice).where(Voice.id == voice_id).execution_options(**FRESH_ROWS)
        return await self.session.scalar(statement)

    async def get_visible(self, user_id: UUID, voice_id: UUID) -> Voice | None:
        statement = select(Voice).where(Voice.id == voice_id, visible_to(user_id)).execution_options(**FRESH_ROWS)
        return await self.session.scalar(statement)

    async def get_owned(self, user_id: UUID, voice_id: UUID) -> Voice | None:
        statement = (
            select(Voice)
            .where(Voice.id == voice_id, Voice.owner_user_id == user_id, Voice.kind == VoiceKind.CLONED.value)
            .execution_options(**FRESH_ROWS)
        )
        return await self.session.scalar(statement)

    async def get_builtin(self, voice_id: UUID) -> Voice | None:
        statement = (
            select(Voice)
            .where(Voice.id == voice_id, Voice.kind == VoiceKind.BUILTIN.value)
            .execution_options(**FRESH_ROWS)
        )
        return await self.session.scalar(statement)

    async def page_visible(
        self, user_id: UUID, voice_filter: VoiceFilter, cursor: Cursor | None, limit: int
    ) -> list[Voice]:
        statement = apply_filter(select(Voice).where(visible_to(user_id)), voice_filter)
        paged = keyset_page(statement, created_at=Voice.created_at, id_=Voice.id, cursor=cursor, limit=limit)
        return list(await self.session.scalars(paged.execution_options(**FRESH_ROWS)))

    async def page_builtin(self, voice_filter: VoiceFilter, cursor: Cursor | None, limit: int) -> list[Voice]:
        statement = apply_filter(select(Voice).where(Voice.kind == VoiceKind.BUILTIN.value), voice_filter)
        paged = keyset_page(statement, created_at=Voice.created_at, id_=Voice.id, cursor=cursor, limit=limit)
        return list(await self.session.scalars(paged.execution_options(**FRESH_ROWS)))

    async def count_cloned(self, user_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(Voice)
            .where(
                Voice.owner_user_id == user_id,
                Voice.kind == VoiceKind.CLONED.value,
                Voice.status != VoiceStatus.FAILED.value,
            )
        )
        return int(await self.session.scalar(statement) or 0)

    async def lock_quota(self, user_id: UUID) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:name, 0))"),
            {"name": f"{QUOTA_LOCK_NAMESPACE}:{user_id}"},
        )

    async def insert_cloned(self, row: NewClonedVoice) -> Voice:
        voice = Voice(
            id=row.id,
            owner_user_id=row.owner_user_id,
            provider=row.provider,
            provider_voice_id=None,
            name=row.name,
            kind=VoiceKind.CLONED.value,
            language=row.language,
            status=VoiceStatus.PENDING.value,
            labels={},
        )
        self.session.add(voice)
        await self.session.flush()
        await self.session.refresh(voice)
        return voice

    async def insert_builtin_if_absent(self, rows: Sequence[NewBuiltinVoice]) -> int:
        added = 0
        for row in rows:
            statement = (
                pg_insert(Voice)
                .values(
                    id=new_id(),
                    owner_user_id=None,
                    provider=row.provider,
                    provider_voice_id=row.provider_voice_id,
                    name=row.name,
                    kind=VoiceKind.BUILTIN.value,
                    language=row.language,
                    status=VoiceStatus.DISABLED.value,
                    labels=dict(row.labels),
                )
                .on_conflict_do_nothing(index_elements=[Voice.provider, Voice.provider_voice_id])
                .returning(Voice.id)
            )
            if await self.session.scalar(statement) is not None:
                added += 1
        return added

    async def set_provider_voice_id(self, voice_id: UUID, provider_voice_id: str) -> bool:
        statement = (
            update(Voice)
            .where(
                Voice.id == voice_id,
                Voice.status == VoiceStatus.PENDING.value,
                Voice.provider_voice_id.is_(None),
            )
            .values(provider_voice_id=provider_voice_id)
            .returning(Voice.id)
        )
        return await self.session.scalar(statement) is not None

    async def mark_ready(self, voice_id: UUID, preview_asset_id: UUID | None) -> bool:
        statement = (
            update(Voice)
            .where(
                Voice.id == voice_id,
                Voice.status == VoiceStatus.PENDING.value,
                Voice.provider_voice_id.is_not(None),
            )
            .values(status=VoiceStatus.READY.value, failure_code=None, preview_asset_id=preview_asset_id)
            .returning(Voice.id)
        )
        return await self.session.scalar(statement) is not None

    async def mark_failed(self, voice_id: UUID, failure_code: str) -> bool:
        statement = (
            update(Voice)
            .where(Voice.id == voice_id, Voice.status == VoiceStatus.PENDING.value)
            .values(status=VoiceStatus.FAILED.value, failure_code=failure_code, provider_voice_id=None)
            .returning(Voice.id)
        )
        return await self.session.scalar(statement) is not None

    async def update_builtin(self, voice_id: UUID, values: Mapping[str, Any]) -> Voice | None:
        statement = (
            update(Voice)
            .where(Voice.id == voice_id, Voice.kind == VoiceKind.BUILTIN.value)
            .values(**values)
            .returning(Voice)
            .execution_options(**FRESH_ROWS)
        )
        return await self.session.scalar(statement)

    async def set_preview(self, voice_id: UUID, asset_id: UUID | None) -> bool:
        statement = update(Voice).where(Voice.id == voice_id).values(preview_asset_id=asset_id).returning(Voice.id)
        return await self.session.scalar(statement) is not None

    async def delete(self, voice_id: UUID, owner_user_id: UUID | None) -> bool:
        statement = (
            delete(Voice)
            .where(
                Voice.id == voice_id,
                Voice.status != VoiceStatus.PENDING.value,
                Voice.owner_user_id.is_not_distinct_from(owner_user_id),
            )
            .returning(Voice.id)
        )
        return await self.session.scalar(statement) is not None

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
        )
        self.session.add(consent)
        await self.session.flush()
        return consent

    async def sample_assets(self, user_id: UUID, voice_id: UUID) -> list[Asset]:
        prefix = f"voice/u/{user_id}/{voice_id}/"
        consent_assets = select(VoiceConsent.consent_asset_id).where(VoiceConsent.voice_reference == voice_id)
        statement = (
            select(Asset)
            .where(
                Asset.owner_user_id == user_id,
                Asset.storage_key.startswith(prefix, autoescape=True),
                Asset.id.not_in(consent_assets),
            )
            .order_by(Asset.storage_key)
            .execution_options(**FRESH_ROWS)
        )
        return list(await self.session.scalars(statement))

    async def cloned_of(self, user_id: UUID) -> list[Voice]:
        statement = (
            select(Voice)
            .where(Voice.owner_user_id == user_id, Voice.kind == VoiceKind.CLONED.value)
            .order_by(Voice.created_at, Voice.id)
            .execution_options(**FRESH_ROWS)
        )
        return list(await self.session.scalars(statement))

    async def consents_of(self, user_id: UUID) -> list[VoiceConsent]:
        statement = (
            select(VoiceConsent)
            .where(VoiceConsent.user_id == user_id)
            .order_by(VoiceConsent.created_at, VoiceConsent.id)
            .execution_options(**FRESH_ROWS)
        )
        return list(await self.session.scalars(statement))

    async def stalled_pending(self, before: datetime, limit: int) -> list[Voice]:
        statement = (
            select(Voice)
            .where(Voice.status == VoiceStatus.PENDING.value, Voice.created_at < before)
            .order_by(Voice.created_at, Voice.id)
            .limit(limit)
            .execution_options(**FRESH_ROWS)
        )
        return list(await self.session.scalars(statement))

    async def abandoned_sample_assets(self, before: datetime, limit: int) -> list[Asset]:
        voice_segment = func.split_part(Asset.storage_key, "/", KEY_VOICE_SEGMENT)
        known_voice = exists().where(cast(Voice.id, Text) == voice_segment)
        evidence = exists().where(
            or_(VoiceConsent.consent_asset_id == Asset.id, cast(VoiceConsent.voice_reference, Text) == voice_segment)
        )
        statement = (
            select(Asset)
            .where(
                Asset.kind == "voice_sample",
                Asset.owner_user_id.is_not(None),
                Asset.created_at < before,
                ~known_voice,
                ~evidence,
            )
            .order_by(Asset.created_at, Asset.id)
            .limit(limit)
            .execution_options(**FRESH_ROWS)
        )
        return list(await self.session.scalars(statement))
