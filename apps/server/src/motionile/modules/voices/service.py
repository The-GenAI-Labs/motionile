import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

import structlog

from motionile.core.clock import Clock
from motionile.core.pagination import Cursor
from motionile.core.storage.base import Storage
from motionile.engine.audio.models import ProviderVoice
from motionile.engine.audio.providers.base import ProviderError, VoiceCatalog, VoiceCloner
from motionile.modules.audit import ActorType, AuditContext, AuditEvent
from motionile.modules.audit import record as record_audit
from motionile.modules.media import AssetInUseError, AssetNotFoundError, AssetService, SpeechService
from motionile.modules.voices.domain import VoiceStatus
from motionile.modules.voices.exceptions import (
    VoiceBusyError,
    VoiceNotFoundError,
    VoicePreviewFailedError,
    VoicePreviewNotReadyError,
    VoiceProviderUnavailableError,
    VoiceUpdateEmptyError,
)
from motionile.modules.voices.models import Voice
from motionile.modules.voices.ports import Transaction
from motionile.modules.voices.preview import PreviewGenerator, delete_provider_voice
from motionile.modules.voices.repository import NewBuiltinVoice, StoreFactory, VoiceFilter
from motionile.modules.voices.schemas import AdminVoiceView, VoicePreviewView, VoiceSyncView, VoiceView
from motionile.modules.voices.views import TAGS_LABEL, admin_voice_view, voice_view

logger = structlog.get_logger(__name__)

AUDIT_TARGET = "voice"
LANGUAGE_PATTERN = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
FALLBACK_LANGUAGE = "en"
MAX_NAME_LENGTH = 80
MAX_PROVIDER_ID_LENGTH = 200
CLONED_CATEGORY = "cloned"
EDITABLE_FIELDS = frozenset({"name", "language", "tags", "status"})


@dataclass(frozen=True, slots=True)
class VoiceSnapshot:
    provider: str
    provider_voice_id: str | None
    language: str
    status: str
    preview_asset_id: UUID | None
    labels: dict[str, Any]


@dataclass(frozen=True, slots=True)
class VoiceListing:
    items: list[VoiceView]
    next_cursor: Cursor | None


@dataclass(frozen=True, slots=True)
class AdminVoiceListing:
    items: list[AdminVoiceView]
    next_cursor: Cursor | None


def next_cursor_of(rows: list[Voice], limit: int) -> Cursor | None:
    shown = rows[:limit]
    if len(rows) > limit and shown:
        return Cursor(shown[-1].created_at, shown[-1].id)
    return None


def normalized_language(value: str | None) -> str:
    if value is None:
        return FALLBACK_LANGUAGE
    candidate = value.strip().replace("_", "-")
    parts = candidate.split("-")
    if parts and parts[0]:
        candidate = "-".join([parts[0].lower(), *parts[1:]])
    return candidate if LANGUAGE_PATTERN.fullmatch(candidate) else FALLBACK_LANGUAGE


def catalog_rows(provider: str, listed: Sequence[ProviderVoice]) -> list[NewBuiltinVoice]:
    rows: dict[str, NewBuiltinVoice] = {}
    for voice in listed:
        provider_voice_id = voice.provider_voice_id
        if not 0 < len(provider_voice_id) <= MAX_PROVIDER_ID_LENGTH or voice.labels.get("category") == CLONED_CATEGORY:
            continue
        name = voice.name.strip()[:MAX_NAME_LENGTH] or provider_voice_id[:MAX_NAME_LENGTH]
        rows.setdefault(
            provider_voice_id,
            NewBuiltinVoice(provider, provider_voice_id, name, normalized_language(voice.language), dict(voice.labels)),
        )
    return list(rows.values())


class VoicesService:
    def __init__(  # noqa: PLR0913
        self,
        *,
        transaction: Transaction,
        store_factory: StoreFactory,
        assets: AssetService,
        storage: Storage,
        speech: SpeechService,
        cloner: Callable[[], VoiceCloner],
        catalog: Callable[[], VoiceCatalog],
        previews: PreviewGenerator,
        clock: Clock,
        preview_ttl: timedelta,
        catalog_provider: str,
    ) -> None:
        self._transaction = transaction
        self._store_factory = store_factory
        self._assets = assets
        self._storage = storage
        self._speech = speech
        self._cloner = cloner
        self._catalog = catalog
        self._previews = previews
        self._clock = clock
        self._preview_ttl = preview_ttl
        self._catalog_provider = catalog_provider

    async def list_voices(
        self, user_id: UUID, voice_filter: VoiceFilter, cursor: Cursor | None, limit: int
    ) -> VoiceListing:
        async with self._transaction() as session:
            rows = await self._store_factory(session).page_visible(user_id, voice_filter, cursor, limit)
        return VoiceListing([voice_view(row) for row in rows[:limit]], next_cursor_of(rows, limit))

    async def get_voice(self, user_id: UUID, voice_id: UUID) -> VoiceView:
        async with self._transaction() as session:
            voice = await self._store_factory(session).get_visible(user_id, voice_id)
        if voice is None:
            raise VoiceNotFoundError
        return voice_view(voice)

    async def preview_url(self, user_id: UUID, voice_id: UUID) -> VoicePreviewView:
        async with self._transaction() as session:
            store = self._store_factory(session)
            voice = await store.get_visible(user_id, voice_id)
            if voice is None:
                raise VoiceNotFoundError
            if voice.preview_asset_id is None:
                raise VoicePreviewNotReadyError
            asset = await self._assets.get(session, None, voice.preview_asset_id)
        url = await self._storage.presigned_get_url(asset.storage_key, expires_in=self._preview_ttl)
        return VoicePreviewView(url=url, expires_at=self._clock.now() + self._preview_ttl)

    async def delete_voice(self, user_id: UUID, voice_id: UUID, context: AuditContext) -> None:
        async with self._transaction() as session:
            voice = await self._store_factory(session).get_owned(user_id, voice_id)
            if voice is None:
                raise VoiceNotFoundError
            if voice.status == VoiceStatus.PENDING.value:
                raise VoiceBusyError
            provider, provider_voice_id = voice.provider, voice.provider_voice_id
        if provider_voice_id is not None:
            try:
                await delete_provider_voice(self._cloner(), provider_voice_id)
            except ProviderError as error:
                logger.warning("voices.provider_delete_failed", voice_id=str(voice_id), code=error.code)
                raise VoiceProviderUnavailableError from error
            await self._speech.delete_cache_for_voice(provider, provider_voice_id)
        await self._remove_rows(user_id, voice_id, context)

    async def _remove_rows(self, user_id: UUID, voice_id: UUID, context: AuditContext) -> None:
        async with self._transaction() as session:
            store = self._store_factory(session)
            voice = await store.get_owned(user_id, voice_id)
            if voice is None:
                return
            samples = await store.sample_assets(user_id, voice_id)
            preview_asset_id = voice.preview_asset_id
            if not await store.delete(voice_id, user_id):
                raise VoiceBusyError
            for sample in samples:
                await self._discard(session, user_id, sample.id)
            if preview_asset_id is not None:
                await self._discard(session, None, preview_asset_id)
            await record_audit(
                session,
                AuditEvent(
                    action="voices.deleted",
                    actor_type=ActorType.USER,
                    actor_user_id=user_id,
                    target_type=AUDIT_TARGET,
                    target_id=str(voice_id),
                    metadata={"samples": len(samples)},
                ),
                context,
            )

    async def _discard(self, session: Any, owner_user_id: UUID | None, asset_id: UUID) -> None:
        try:
            await self._assets.delete(session, owner_user_id, asset_id)
        except (AssetNotFoundError, AssetInUseError):
            logger.warning("voices.asset_not_removed", asset_id=str(asset_id))

    async def admin_list(self, voice_filter: VoiceFilter, cursor: Cursor | None, limit: int) -> AdminVoiceListing:
        async with self._transaction() as session:
            rows = await self._store_factory(session).page_builtin(voice_filter, cursor, limit)
        return AdminVoiceListing([admin_voice_view(row) for row in rows[:limit]], next_cursor_of(rows, limit))

    async def admin_sync(self, actor_id: UUID, context: AuditContext) -> VoiceSyncView:
        try:
            listed = await self._catalog().list_voices()
        except ProviderError as error:
            logger.warning("voices.catalog_sync_failed", code=error.code)
            raise VoiceProviderUnavailableError from error
        rows = catalog_rows(self._catalog_provider, listed)
        async with self._transaction() as session:
            added = await self._store_factory(session).insert_builtin_if_absent(rows)
            await record_audit(
                session,
                self._admin_event(actor_id, "voices.synced", None, {"added": added, "listed": len(rows)}),
                context,
            )
        return VoiceSyncView(added=added, unchanged=len(rows) - added)

    async def admin_update(
        self, actor_id: UUID, voice_id: UUID, changes: dict[str, Any], context: AuditContext
    ) -> AdminVoiceView:
        values = {name: value for name, value in changes.items() if name in EDITABLE_FIELDS}
        if not values:
            raise VoiceUpdateEmptyError
        async with self._transaction() as session:
            voice = await self._store_factory(session).get_builtin(voice_id)
            if voice is None:
                raise VoiceNotFoundError
            current = VoiceSnapshot(
                provider=voice.provider,
                provider_voice_id=voice.provider_voice_id,
                language=voice.language,
                status=voice.status,
                preview_asset_id=voice.preview_asset_id,
                labels=dict(voice.labels),
            )
        language = str(values.get("language", current.language))
        target_status = VoiceStatus(values["status"]).value if "status" in values else current.status
        needs_preview = target_status == VoiceStatus.READY.value and (
            current.preview_asset_id is None or language != current.language
        )
        columns: dict[str, Any] = {}
        if "name" in values:
            columns["name"] = values["name"]
        if "language" in values:
            columns["language"] = language
        if "tags" in values:
            columns["labels"] = {**current.labels, TAGS_LABEL: list(dict.fromkeys(values["tags"]))}
        if "status" in values:
            columns["status"] = target_status
        if needs_preview:
            columns["preview_asset_id"] = await self._generate_preview(
                voice_id, current.provider, current.provider_voice_id, language, actor_id
            )
        async with self._transaction() as session:
            row = await self._store_factory(session).update_builtin(voice_id, columns)
            if row is None:
                raise VoiceNotFoundError
            await record_audit(
                session,
                self._admin_event(actor_id, "voices.updated", voice_id, {"fields": sorted(values)}),
                context,
            )
            return admin_voice_view(row)

    async def admin_regenerate_preview(self, actor_id: UUID, voice_id: UUID, context: AuditContext) -> AdminVoiceView:
        async with self._transaction() as session:
            voice = await self._store_factory(session).get_builtin(voice_id)
            if voice is None:
                raise VoiceNotFoundError
            provider, provider_voice_id, language = voice.provider, voice.provider_voice_id, voice.language
        asset_id = await self._generate_preview(voice_id, provider, provider_voice_id, language, actor_id)
        async with self._transaction() as session:
            store = self._store_factory(session)
            if not await store.set_preview(voice_id, asset_id):
                raise VoiceNotFoundError
            row = await store.get_builtin(voice_id)
            if row is None:
                raise VoiceNotFoundError
            await record_audit(
                session, self._admin_event(actor_id, "voices.preview_regenerated", voice_id, {}), context
            )
            return admin_voice_view(row)

    async def _generate_preview(
        self, voice_id: UUID, provider: str, provider_voice_id: str | None, language: str, actor_id: UUID
    ) -> UUID:
        if provider_voice_id is None:
            raise VoicePreviewFailedError
        try:
            asset = await self._previews.generate(voice_id, provider, provider_voice_id, language, user_id=actor_id)
        except ProviderError as error:
            logger.warning("voices.preview_failed", voice_id=str(voice_id), code=error.code)
            raise VoicePreviewFailedError from error
        return asset.id

    @staticmethod
    def _admin_event(actor_id: UUID, action: str, voice_id: UUID | None, metadata: dict[str, Any]) -> AuditEvent:
        return AuditEvent(
            action=action,
            actor_type=ActorType.ADMIN,
            actor_user_id=actor_id,
            target_type=AUDIT_TARGET,
            target_id=str(voice_id) if voice_id is not None else None,
            metadata=metadata,
        )
