import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.audio.subtitles import render_srt, render_webvtt
from motionile.engine.render.models import Aspect
from motionile.engine.render.thumbnails import PosterFiles
from motionile.modules.media.assets import AssetSpec, AssetView
from motionile.modules.media.domain import AssetKind, RenderStage
from motionile.modules.media.keys import poster_key, rendition_key, subtitles_key
from motionile.modules.media.pipeline.captions import narration_cues
from motionile.modules.media.pipeline.context import PipelineDeps, RenderRun, StageResult
from motionile.modules.media.pipeline.ports import PosterJob
from motionile.modules.media.pipeline.stages.encoding import video_key
from motionile.modules.media.pipeline.workspace import file_chunks
from motionile.modules.media.render_repository import NewRendition

VIDEO_TYPE = "video/mp4"
WEBP_TYPE = "image/webp"
JPEG_TYPE = "image/jpeg"
VTT_TYPE = "text/vtt"
SRT_TYPE = "application/x-subrip"
MS_PER_SECOND = 1000


@dataclass(frozen=True)
class FinishedAspect:
    aspect: Aspect
    video: Path
    posters: PosterFiles
    duration_ms: int


def video_duration_ms(frames: int, fps: int) -> int:
    return round(frames * MS_PER_SECOND / fps)


class FinalizingStage:
    stage = RenderStage.FINALIZING

    def __init__(self, deps: PipelineDeps) -> None:
        self._deps = deps

    async def execute(self, run: RenderRun) -> StageResult:
        narration = await run.load_narration()
        toolchain = run.toolchain
        fps = run.options.fps
        finished: list[FinishedAspect] = []
        for position, aspect in enumerate(run.options.engine_aspects):
            await run.checkpoint()
            plan = toolchain.plan_segments(narration, aspect, run.workspace.path("segments"))
            video = await run.workspace.fetch(
                video_key(run, aspect), run.workspace.path("video", f"{aspect.label}.mp4")
            )
            duration = video_duration_ms(plan.total_frames, fps)
            posters = await toolchain.posters(PosterJob(video, run.workspace.path("posters"), aspect, duration))
            finished.append(FinishedAspect(aspect, video, posters, duration))
            await run.progress.update(RenderStage.FINALIZING, (position + 1) / (len(run.options.aspects) + 1))
        subtitles = await self._subtitle_files(run, narration) if run.options.subtitles else None

        async def commit(session: AsyncSession) -> dict[str, Any]:
            return await self._publish(session, run, finished, subtitles, narration.total_duration_ms)

        return StageResult(keys={}, columns={"duration_ms": narration.total_duration_ms}, commit=commit)

    async def _subtitle_files(self, run: RenderRun, narration: NarrationDocument) -> tuple[Path, Path]:
        cues = narration_cues(narration)
        directory = run.workspace.path("subtitles")
        await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
        vtt, srt = directory / "subtitles.vtt", directory / "subtitles.srt"
        await asyncio.to_thread(vtt.write_bytes, render_webvtt(cues).encode("utf-8"))
        await asyncio.to_thread(srt.write_bytes, render_srt(cues).encode("utf-8"))
        return vtt, srt

    async def _publish(
        self,
        session: AsyncSession,
        run: RenderRun,
        finished: list[FinishedAspect],
        subtitles: tuple[Path, Path] | None,
        narration_ms: int,
    ) -> dict[str, Any]:
        store = self._deps.store_factory(session)
        owner, render_id = run.owner_id, run.render_id
        for item in finished:
            label = item.aspect.value
            viewport = item.aspect.spec.viewport
            video = await self._store(
                session,
                item.video,
                AssetSpec(
                    key=rendition_key(owner, render_id, label),
                    kind=AssetKind.VIDEO,
                    content_type=VIDEO_TYPE,
                    duration_ms=item.duration_ms,
                    owner_user_id=owner,
                    width=viewport.width,
                    height=viewport.height,
                ),
            )
            webp = await self._store(
                session,
                item.posters.webp,
                AssetSpec(
                    key=poster_key(owner, render_id, label, "webp"),
                    kind=AssetKind.THUMBNAIL,
                    content_type=WEBP_TYPE,
                    owner_user_id=owner,
                    width=viewport.width,
                    height=viewport.height,
                ),
            )
            jpeg = await self._store(
                session,
                item.posters.jpeg,
                AssetSpec(
                    key=poster_key(owner, render_id, label, "jpg"),
                    kind=AssetKind.THUMBNAIL,
                    content_type=JPEG_TYPE,
                    owner_user_id=owner,
                    width=viewport.width,
                    height=viewport.height,
                ),
            )
            await store.add_rendition(
                NewRendition(
                    render_id=render_id,
                    aspect=label,
                    width=viewport.width,
                    height=viewport.height,
                    asset_id=video.id,
                    poster_webp_asset_id=webp.id,
                    poster_jpeg_asset_id=jpeg.id,
                    duration_ms=item.duration_ms,
                    burned_in_subtitles=run.options.burn_in_subtitles,
                )
            )
        columns: dict[str, Any] = {"duration_ms": narration_ms}
        if subtitles is not None:
            for column, path, extension, content_type in (
                ("subtitles_vtt_asset_id", subtitles[0], "vtt", VTT_TYPE),
                ("subtitles_srt_asset_id", subtitles[1], "srt", SRT_TYPE),
            ):
                spec = AssetSpec(
                    key=subtitles_key(owner, render_id, extension),
                    kind=AssetKind.SUBTITLE,
                    content_type=content_type,
                    owner_user_id=owner,
                )
                columns[column] = (await self._store(session, path, spec)).id
        return columns

    async def _store(self, session: AsyncSession, path: Path, spec: AssetSpec) -> AssetView:
        return await self._deps.assets.store_chunks(session, file_chunks(path), spec)
