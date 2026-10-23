from pathlib import Path

from motionile.core.storage.base import ObjectNotFoundError
from motionile.engine.audio.narration import SceneAudio, assemble_narration
from motionile.modules.media.domain import RenderFailureCode, RenderStage
from motionile.modules.media.pipeline.context import (
    NARRATION,
    PADDING_FIELD,
    UPLOAD_CHECKPOINT,
    PipelineDeps,
    RenderRun,
    StageResult,
)
from motionile.modules.media.pipeline.failures import RenderFailedError
from motionile.modules.media.pipeline.narrator import SceneNarrator
from motionile.modules.media.render_options import SceneScript, SynthesizeNarration, UploadedScene

NARRATION_NAME = "narration.json"
WAV_CONTENT_TYPE = "audio/wav"
JSON_CONTENT_TYPE = "application/json"


def scene_name(index: int) -> str:
    return f"scene-{index}.wav"


class VoicingStage:
    stage = RenderStage.VOICING

    def __init__(self, deps: PipelineDeps) -> None:
        self._deps = deps

    async def execute(self, run: RenderRun) -> StageResult:
        deps = self._deps
        padding = deps.settings.render.scene_padding_ms
        limit = deps.settings.render.max_duration_ms
        narration = run.options.narration
        narrator = SceneNarrator(deps.speech, run.toolchain, deps.transcriber, run.toolchain.config.tools)
        scenes: list[SceneAudio] = []
        spoken_ms = 0
        total = len(narration.scenes)
        for index, scene in enumerate(narration.scenes):
            await run.checkpoint()
            destination = run.workspace.path(scene_name(index))
            if isinstance(narration, SynthesizeNarration) and isinstance(scene, SceneScript):
                audio = await narrator.synthesized(
                    run.owner_id, narration.voice, scene.scene_id, scene.text, destination
                )
            elif isinstance(scene, UploadedScene):
                audio = await self._uploaded(run, narrator, scene, destination)
            else:
                raise TypeError("the narration scene does not match the narration mode")
            scenes.append(audio)
            spoken_ms += audio.duration_ms + (padding if index < total - 1 else 0)
            if spoken_ms > limit:
                raise RenderFailedError(
                    RenderFailureCode.DURATION_LIMIT_EXCEEDED,
                    f"The narration lasts at least {spoken_ms} ms; the limit is {limit} ms.",
                )
            await run.progress.update(RenderStage.VOICING, (index + 1) / total)
        document = assemble_narration(scenes, padding)
        keys: dict[str, str] = {}
        for index in range(total):
            key = run.workspace.key(scene_name(index))
            await run.workspace.put_file(key, run.workspace.path(scene_name(index)), WAV_CONTENT_TYPE)
            keys[f"scene-{index}"] = key
        narration_key = run.workspace.key(NARRATION_NAME)
        await run.workspace.put_bytes(
            narration_key, document.model_dump_json(by_alias=True).encode("utf-8"), JSON_CONTENT_TYPE
        )
        keys[NARRATION] = narration_key
        run.narration = document
        return StageResult(
            keys=keys,
            data={PADDING_FIELD: padding, "durationMs": document.total_duration_ms},
            columns={"duration_ms": document.total_duration_ms},
        )

    async def _uploaded(
        self, run: RenderRun, narrator: SceneNarrator, scene: UploadedScene, destination: Path
    ) -> SceneAudio:
        key = run.checkpoint_keys(UPLOAD_CHECKPOINT).get(scene.scene_id)
        if key is None:
            raise ObjectNotFoundError(scene.scene_id)
        source = await run.workspace.get_bytes(key)
        return await narrator.uploaded(scene.scene_id, scene.text, source, key.rsplit("/", 1)[-1], destination)
