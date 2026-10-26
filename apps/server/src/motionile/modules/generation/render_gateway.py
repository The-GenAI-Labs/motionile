import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Final, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.engine.ai.ports import JobSnapshot, NarrationScript, RenderProgress
from motionile.modules.generation.pipeline_repository import SqlPipelineRepository
from motionile.modules.media import (
    Aspect,
    RenderOptions,
    RenderOptionsRequest,
    RenderSource,
    RenderStatus,
    RenderView,
    SceneScript,
    SynthesizeRequest,
    VoiceLookup,
    is_terminal,
    resolve_render_options,
)
from motionile.modules.media import RenderProgress as RenderMessage

type Transaction = Callable[[], AbstractAsyncContextManager[AsyncSession]]

POLL_SECONDS: Final = 1.0
RECHECK_SECONDS: Final = 5.0
CANCELLED_CODE: Final = "render_cancelled"
FAILED_STATUSES: Final = frozenset({RenderStatus.FAILED, RenderStatus.CANCELLED})


class RenderFeed(Protocol):
    async def next(self, timeout_seconds: float) -> RenderMessage | None: ...


class RenderChannel(Protocol):
    def subscribe(self, render_id: UUID) -> AbstractAsyncContextManager[RenderFeed]: ...


class RenderLinks(Protocol):
    async def owner_of_render(self, render_id: UUID) -> UUID | None: ...

    async def attach_render(self, job_id: UUID, render_id: UUID) -> None: ...


class RenderMedia(Protocol):
    async def create_render(
        self, session: AsyncSession, user_id: UUID, composition_html: str, options: RenderOptions, source: RenderSource
    ) -> RenderView: ...

    async def get_render(self, session: AsyncSession, user_id: UUID, render_id: UUID) -> RenderView: ...

    async def cancel_render(self, session: AsyncSession, user_id: UUID, render_id: UUID) -> RenderView: ...


class RenderOwnerNotFoundError(LookupError):
    def __init__(self, render_id: UUID) -> None:
        super().__init__(f"no job owns the render {render_id}")


def progress_of(
    render_id: UUID, status: RenderStatus, stage: str | None, progress: int, error_code: str | None
) -> RenderProgress:
    failed = status in FAILED_STATUSES
    code = error_code or (CANCELLED_CODE if status is RenderStatus.CANCELLED else None)
    return RenderProgress(
        render_id=render_id,
        status=status.value,
        stage=stage,
        progress=progress,
        terminal=is_terminal(status),
        failed=failed,
        error_code=code if failed else None,
    )


def progress_from_message(message: RenderMessage) -> RenderProgress:
    return progress_of(
        message.render_id,
        message.status,
        message.stage.value if message.stage is not None else None,
        message.progress,
        message.error_code,
    )


class MediaRenderGateway:
    def __init__(  # noqa: PLR0913
        self,
        transaction: Transaction,
        media: RenderMedia,
        channel: RenderChannel,
        voices: VoiceLookup,
        *,
        default_fps: int,
        links: Callable[[AsyncSession], RenderLinks] = SqlPipelineRepository,
        poll_seconds: float = POLL_SECONDS,
        recheck_seconds: float = RECHECK_SECONDS,
    ) -> None:
        self._transaction = transaction
        self._media = media
        self._channel = channel
        self._voices = voices
        self._default_fps = default_fps
        self._links = links
        self._poll_seconds = poll_seconds
        self._recheck_seconds = recheck_seconds

    async def start(self, job: JobSnapshot, html: str, scenes: Sequence[NarrationScript]) -> UUID:
        options = job.options
        request = RenderOptionsRequest(
            aspects=[Aspect(aspect) for aspect in options.aspects],
            narration=SynthesizeRequest(
                mode="synthesize",
                voice_id=options.voice_id,
                scenes=[SceneScript(scene_id=scene.scene_id, text=scene.text) for scene in scenes],
            ),
            music_track_id=options.music_track_id,
            subtitles=options.subtitles,
            burn_in_subtitles=options.burn_in_subtitles,
        )
        async with self._transaction() as session:
            resolved = await resolve_render_options(
                session, job.user_id, request, self._voices, default_fps=self._default_fps
            )
            view = await self._media.create_render(session, job.user_id, html, resolved, RenderSource.JOB)
            await self._links(session).attach_render(job.id, view.id)
        return view.id

    async def follow(self, render_id: UUID) -> AsyncIterator[RenderProgress]:
        owner = await self._owner(render_id)
        async with self._channel.subscribe(render_id) as subscription:
            state = await self._state(owner, render_id)
            yield state
            if state.terminal:
                return
            loop = asyncio.get_running_loop()
            last_checked = loop.time()
            while True:
                message = await subscription.next(self._poll_seconds)
                if message is not None:
                    update = progress_from_message(message)
                    yield update
                    if update.terminal:
                        return
                    continue
                now = loop.time()
                if now - last_checked >= self._recheck_seconds:
                    last_checked = now
                    state = await self._state(owner, render_id)
                    yield state
                    if state.terminal:
                        return

    async def cancel(self, render_id: UUID) -> None:
        owner = await self._owner(render_id)
        async with self._transaction() as session:
            await self._media.cancel_render(session, owner, render_id)

    async def _owner(self, render_id: UUID) -> UUID:
        async with self._transaction() as session:
            owner = await self._links(session).owner_of_render(render_id)
        if owner is None:
            raise RenderOwnerNotFoundError(render_id)
        return owner

    async def _state(self, owner: UUID, render_id: UUID) -> RenderProgress:
        async with self._transaction() as session:
            view = await self._media.get_render(session, owner, render_id)
        return progress_of(
            render_id,
            view.status,
            view.stage.value if view.stage is not None else None,
            view.progress,
            view.error_code,
        )
