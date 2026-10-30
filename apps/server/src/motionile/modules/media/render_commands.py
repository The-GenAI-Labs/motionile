import asyncio
import shutil
import tempfile
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import structlog
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import Clock
from motionile.core.config import Settings
from motionile.core.db import after_commit, after_rollback
from motionile.core.ids import new_id
from motionile.core.pagination import Cursor
from motionile.core.storage.base import Storage
from motionile.engine.audio.audio_validation import AudioRejectedError, Container, ValidatedAudio
from motionile.engine.audio.narration import SceneAudio, assemble_narration
from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.audio.providers.base import Transcriber
from motionile.modules.audit import ActorType, AuditContext, AuditEvent
from motionile.modules.audit import record as record_audit
from motionile.modules.media.assets import AssetService, AssetSpec
from motionile.modules.media.domain import AssetKind, RenderSource, RenderStatus, is_terminal
from motionile.modules.media.exceptions import (
    CompositionTooLargeError,
    RenderAudioRejectedError,
    RenderNotFoundError,
    RenderOptionsInvalidError,
)
from motionile.modules.media.keys import composition_key, render_work_key
from motionile.modules.media.music import MusicService
from motionile.modules.media.music_repository import MusicFilter
from motionile.modules.media.pipeline.narrator import FfmpegNormalizer, SceneNarrator
from motionile.modules.media.pipeline.ports import AudioNormalizer, SpeechPort
from motionile.modules.media.pipeline.workspace import bytes_chunks
from motionile.modules.media.providers import ffmpeg_tools
from motionile.modules.media.render_events import RenderEvents, RenderProgress
from motionile.modules.media.render_options import (
    MAX_SCENES,
    RenderOptions,
    ResolvedVoice,
    SceneScript,
    SynthesizeNarration,
    UploadNarration,
)
from motionile.modules.media.render_repository import NewRender, RenderJobStore, SqlRenderJobRepository
from motionile.modules.media.render_view import render_view
from motionile.modules.media.schemas import MusicTrackView, RenderView

type JobStoreFactory = Callable[[AsyncSession], RenderJobStore]
type RenderDispatch = Callable[[AsyncSession, UUID], None]
type AudioCheck = Callable[[bytes], Awaitable[ValidatedAudio]]

COMPOSITION_MAX_BYTES = 4 * 1024 * 1024
UPLOAD_MAX_BYTES = 25 * 1024 * 1024
UPLOAD_MIN_DURATION_MS = 300
UPLOAD_CHECKPOINT = "upload"
MUSIC_PAGE_SIZE = 100
MUSIC_PAGES = 5
AUDIT_TARGET = "render"
CONTENT_TYPES: Mapping[Container, tuple[str, str]] = {
    "wav": ("wav", "audio/wav"),
    "mp3": ("mp3", "audio/mpeg"),
    "aac": ("aac", "audio/aac"),
    "ogg": ("ogg", "audio/ogg"),
    "flac": ("flac", "audio/flac"),
    "mp4": ("m4a", "audio/mp4"),
    "matroska": ("mka", "audio/x-matroska"),
}

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RenderCommandPorts:
    assets: AssetService
    music: MusicService
    storage: Storage
    events: RenderEvents
    settings: Settings
    clock: Clock
    dispatch: RenderDispatch
    audio_check: AudioCheck
    speech: SpeechPort
    transcriber: Transcriber
    store_factory: JobStoreFactory = SqlRenderJobRepository
    normalizer: AudioNormalizer | None = None


class RenderCommands:
    def __init__(self, ports: RenderCommandPorts) -> None:
        self._assets = ports.assets
        self._music = ports.music
        self._storage = ports.storage
        self._events = ports.events
        self._settings = ports.settings
        self._clock = ports.clock
        self._dispatch = ports.dispatch
        self._audio_check = ports.audio_check
        self._store_factory = ports.store_factory
        tools = ffmpeg_tools(ports.settings)
        self._narrator = SceneNarrator(
            ports.speech, ports.normalizer or FfmpegNormalizer(tools), ports.transcriber, tools
        )

    async def create_render(  # noqa: PLR0913
        self,
        session: AsyncSession,
        user_id: UUID,
        composition_html: str,
        options: RenderOptions,
        source: RenderSource,
        *,
        audio_uploads: Mapping[str, bytes] | None = None,
        context: AuditContext | None = None,
    ) -> RenderView:
        uploads = dict(audio_uploads or {})
        composition = composition_html.encode("utf-8")
        if len(composition) > COMPOSITION_MAX_BYTES:
            raise CompositionTooLargeError
        self._check_uploads(options, uploads)
        if options.music_track_id is not None:
            await self._music.require_active(session, options.music_track_id)
        stored = await self._validated_uploads(options, uploads)
        render_id = new_id()
        asset = await self._assets.store_bytes(
            session,
            composition,
            AssetSpec(
                key=composition_key(user_id, render_id),
                kind=AssetKind.HTML,
                content_type="text/plain",
                owner_user_id=user_id,
            ),
        )
        keys = await self._store_uploads(session, render_id, stored)
        checkpoints = {UPLOAD_CHECKPOINT: {"completedAt": self._clock.now().isoformat(), "keys": keys}} if keys else {}
        row = await self._store_factory(session).insert(
            NewRender(
                id=render_id,
                owner_user_id=user_id,
                source=source.value,
                options=options.model_dump(mode="json", by_alias=True),
                composition_asset_id=asset.id,
                checkpoints=checkpoints,
            )
        )
        if source is RenderSource.TESTBED:
            await record_audit(
                session,
                AuditEvent(
                    action="render.testbed_created",
                    actor_type=ActorType.ADMIN,
                    actor_user_id=user_id,
                    target_type=AUDIT_TARGET,
                    target_id=str(render_id),
                    metadata={
                        "aspects": [aspect.value for aspect in options.aspects],
                        "mode": options.narration.mode,
                        "scenes": len(options.narration.scenes),
                    },
                ),
                context,
            )
        self._dispatch(session, render_id)
        return render_view(row)

    async def cancel_render(self, session: AsyncSession, user_id: UUID, render_id: UUID) -> RenderView:
        outcome = await self._store_factory(session).request_cancel(user_id, render_id, self._clock.now())
        if outcome is None:
            raise RenderNotFoundError
        render = outcome.render
        if not is_terminal(RenderStatus(render.status)) or outcome.cancelled_now:
            after_commit(session, lambda: self._events.flag_cancel(render_id))
        if outcome.cancelled_now:
            message = RenderProgress(
                render_id=render_id,
                status=RenderStatus.CANCELLED,
                stage=None,
                progress=render.progress,
                at=self._clock.now(),
            )
            after_commit(session, lambda: self._events.publish(message))
        return render_view(render)

    async def narrate(  # noqa: PLR0913
        self,
        session: AsyncSession,
        user_id: UUID,
        scenes: Sequence[SceneScript],
        voice: ResolvedVoice,
        *,
        padding_ms: int | None = None,
        job_id: UUID | None = None,
    ) -> NarrationDocument:
        del session
        try:
            script = SynthesizeNarration(mode="synthesize", voice=voice, scenes=list(scenes))
        except ValidationError as error:
            raise RenderOptionsInvalidError(f"The scenes are invalid: {error.error_count()} problem(s).") from None
        padding = padding_ms if padding_ms is not None else self._settings.render.scene_padding_ms
        limit = self._settings.render.max_duration_ms
        parent = self._settings.render.work_directory
        if parent is not None:
            await asyncio.to_thread(parent.mkdir, parents=True, exist_ok=True)
        root = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="mn-", dir=parent))
        try:
            audio: list[SceneAudio] = []
            for index, scene in enumerate(script.scenes):
                destination = root / f"scene-{index}.wav"
                audio.append(
                    await self._narrator.synthesized(
                        user_id, voice, scene.scene_id, scene.text, destination, job_id=job_id
                    )
                )
            document = assemble_narration(audio, padding)
        finally:
            await asyncio.to_thread(shutil.rmtree, root, True)
        if document.total_duration_ms > limit:
            raise RenderOptionsInvalidError(
                f"The narration lasts {document.total_duration_ms} ms; the limit is {limit} ms.",
                code="duration_limit_exceeded",
            )
        return document

    async def selectable_music(self, session: AsyncSession) -> list[MusicTrackView]:
        tracks: list[MusicTrackView] = []
        cursor: Cursor | None = None
        for _ in range(MUSIC_PAGES):
            page = await self._music.list_tracks(session, MusicFilter(None, True), cursor, MUSIC_PAGE_SIZE)
            tracks.extend(page.items)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        return tracks

    @staticmethod
    def _check_uploads(options: RenderOptions, uploads: Mapping[str, bytes]) -> None:
        if isinstance(options.narration, UploadNarration):
            wanted = {scene.audio_part for scene in options.narration.scenes}
            missing = sorted(wanted - set(uploads))
            extra = sorted(set(uploads) - wanted)
            if missing or extra:
                raise RenderOptionsInvalidError(
                    f"The audio parts do not match the scenes: missing {missing}, unexpected {extra}."
                )
        elif uploads:
            raise RenderOptionsInvalidError("Audio parts are only accepted with an uploaded narration.")
        if len(options.narration.scenes) > MAX_SCENES:
            raise RenderOptionsInvalidError("There are too many scenes.")

    async def _validated_uploads(
        self, options: RenderOptions, uploads: Mapping[str, bytes]
    ) -> dict[str, tuple[str, str, bytes]]:
        stored: dict[str, tuple[str, str, bytes]] = {}
        for scene in options.uploaded_scenes:
            data = uploads[scene.audio_part]
            if len(data) > UPLOAD_MAX_BYTES:
                raise RenderAudioRejectedError(
                    f"The audio for scene {scene.scene_id} is too large.", extensions={"reason": "too_large"}
                )
            try:
                checked = await self._audio_check(data)
            except AudioRejectedError as error:
                raise RenderAudioRejectedError(
                    f"The audio for scene {scene.scene_id} was rejected: {error.message}.",
                    extensions={"reason": error.code},
                ) from None
            extension, content_type = CONTENT_TYPES[checked.container]
            stored[scene.scene_id] = (extension, content_type, data)
        return stored

    async def _store_uploads(
        self, session: AsyncSession, render_id: UUID, stored: Mapping[str, tuple[str, str, bytes]]
    ) -> dict[str, str]:
        keys: dict[str, str] = {}
        for scene_id, (extension, content_type, data) in stored.items():
            key = render_work_key(render_id, f"upload-{scene_id}.{extension}")
            await self._storage.put(key, bytes_chunks(data), content_type=content_type)
            after_rollback(session, lambda key=key: self._storage.delete(key))
            keys[scene_id] = key
        return keys
