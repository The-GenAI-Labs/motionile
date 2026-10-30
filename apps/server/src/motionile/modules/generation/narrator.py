from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Final, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.engine.ai.graphs.errors import PipelineErrorCode, pipeline_error
from motionile.engine.ai.ports import JobSnapshot, NarrationScript
from motionile.engine.audio.narration import NarrationError
from motionile.engine.audio.narration_models import NarrationDocument
from motionile.modules.media import RenderOptionsInvalidError, ResolvedVoice, SceneScript, VoiceLookup

type Transaction = Callable[[], AbstractAsyncContextManager[AsyncSession]]
type SessionFactory = Callable[[], AsyncSession]

DURATION_LIMIT_CODE: Final = "duration_limit_exceeded"


class NarrationMedia(Protocol):
    async def narrate(  # noqa: PLR0913
        self,
        session: AsyncSession,
        user_id: UUID,
        scenes: Sequence[SceneScript],
        voice: ResolvedVoice,
        *,
        padding_ms: int | None = None,
        job_id: UUID | None = None,
    ) -> NarrationDocument: ...


class MediaNarrator:
    def __init__(
        self, transaction: Transaction, new_session: SessionFactory, media: NarrationMedia, voices: VoiceLookup
    ) -> None:
        self._transaction = transaction
        self._new_session = new_session
        self._media = media
        self._voices = voices

    async def narrate(self, job: JobSnapshot, scenes: Sequence[NarrationScript]) -> NarrationDocument:
        async with self._transaction() as session:
            voice = await self._voices.resolve_selectable(session, job.user_id, job.options.voice_id)
        scripts = [SceneScript(scene_id=scene.scene_id, text=scene.text) for scene in scenes]
        idle = self._new_session()
        try:
            return await self._media.narrate(idle, job.user_id, scripts, voice, job_id=job.id)
        except RenderOptionsInvalidError as error:
            if error.code == DURATION_LIMIT_CODE:
                raise pipeline_error(PipelineErrorCode.DURATION_LIMIT_EXCEEDED) from None
            raise NarrationError(error.detail or "the scenes could not be narrated") from None
        finally:
            await idle.close()
