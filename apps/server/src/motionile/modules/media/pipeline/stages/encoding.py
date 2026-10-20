import asyncio
from pathlib import Path

from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.audio.subtitles import parse_aspect, render_ass
from motionile.engine.render.models import Aspect
from motionile.modules.media.domain import RenderStage
from motionile.modules.media.keys import mixed_audio_key
from motionile.modules.media.pipeline.captions import narration_cues
from motionile.modules.media.pipeline.context import PipelineDeps, RenderRun, StageResult
from motionile.modules.media.pipeline.ports import AssembleJob
from motionile.modules.media.pipeline.stages.capturing import segment_key

VIDEO_CONTENT_TYPE = "video/mp4"


def video_key(run: RenderRun, aspect: Aspect) -> str:
    return run.workspace.key("video", f"{aspect.label}.mp4")


class EncodingStage:
    stage = RenderStage.ENCODING

    def __init__(self, deps: PipelineDeps) -> None:
        self._deps = deps

    async def execute(self, run: RenderRun) -> StageResult:
        narration = await run.load_narration()
        aspects = run.options.engine_aspects
        keys: dict[str, str] = {}
        for position, aspect in enumerate(aspects):
            await run.checkpoint()
            key = video_key(run, aspect)
            if not await run.workspace.exists(key):
                await self._encode(run, aspect, narration, key)
            keys[aspect.label] = key
            await run.progress.update(RenderStage.ENCODING, (position + 1) / len(aspects))
        return StageResult(keys=keys)

    async def _encode(self, run: RenderRun, aspect: Aspect, narration: NarrationDocument, key: str) -> None:
        toolchain = run.toolchain
        plan = toolchain.plan_segments(narration, aspect, run.workspace.path("segments"))
        for index, path in enumerate(plan.segments):
            await run.workspace.fetch(segment_key(run, aspect, index), path)
        audio = await run.workspace.fetch(mixed_audio_key(run.owner_id, run.render_id), run.workspace.path("audio.m4a"))
        ass_path: Path | None = None
        fonts_directory: Path | None = None
        if run.options.burn_in_subtitles:
            ass_path = run.workspace.path("subtitles", f"{aspect.label}.ass")
            await asyncio.to_thread(ass_path.parent.mkdir, parents=True, exist_ok=True)
            document = render_ass(narration_cues(narration), parse_aspect(aspect.value))
            await asyncio.to_thread(ass_path.write_bytes, document.encode("utf-8"))
            fonts_directory = await toolchain.write_fonts(run.workspace.path("fonts"))
        output = await toolchain.assemble(
            AssembleJob(
                segments=plan.segments,
                audio=audio,
                aspect=aspect,
                total_frames=plan.total_frames,
                directory=run.workspace.path("video"),
                ass_path=ass_path,
                fonts_directory=fonts_directory,
            )
        )
        await run.workspace.put_file(key, output, VIDEO_CONTENT_TYPE)
