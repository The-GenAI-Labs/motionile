from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.engine.audio.mix import MixPlan, MusicBed
from motionile.modules.media.assets import AssetSpec
from motionile.modules.media.domain import AssetKind, RenderStage
from motionile.modules.media.keys import mixed_audio_key
from motionile.modules.media.pipeline.context import PADDING_FIELD, PipelineDeps, RenderRun, StageResult
from motionile.modules.media.pipeline.stages.voicing import scene_name
from motionile.modules.media.pipeline.workspace import file_chunks

MIXED_CONTENT_TYPE = "audio/mp4"
AUDIO_NAME = "audio.m4a"
MUSIC_NAME = "music.m4a"


class MixingStage:
    stage = RenderStage.MIXING

    def __init__(self, deps: PipelineDeps) -> None:
        self._deps = deps

    async def execute(self, run: RenderRun) -> StageResult:
        deps = self._deps
        narration = await run.load_narration()
        scene_keys = run.checkpoint_keys(RenderStage.VOICING.value)
        paths = [
            await run.workspace.fetch(scene_keys[f"scene-{index}"], run.workspace.path(scene_name(index)))
            for index in range(len(narration.scenes))
        ]
        await run.checkpoint()
        music = await self._music(run)
        tail_ms = run.toolchain.config.tail_ms
        recorded = run.checkpoint_value(RenderStage.VOICING.value, PADDING_FIELD)
        plan = MixPlan(
            scene_paths=tuple(paths),
            padding_ms=int(recorded) if recorded is not None else deps.settings.render.scene_padding_ms,
            total_ms=narration.total_duration_ms + tail_ms,
            tail_ms=tail_ms,
            music=music,
        )
        destination = run.workspace.path(AUDIO_NAME)
        await run.toolchain.mix(plan, destination)
        await run.progress.update(RenderStage.MIXING, 1.0)
        key = mixed_audio_key(run.owner_id, run.render_id)

        async def commit(session: AsyncSession) -> dict[str, Any]:
            asset = await deps.assets.store_chunks(
                session,
                file_chunks(destination),
                AssetSpec(
                    key=key,
                    kind=AssetKind.AUDIO,
                    content_type=MIXED_CONTENT_TYPE,
                    owner_user_id=run.owner_id,
                    duration_ms=plan.total_ms,
                ),
            )
            return {"mixed_audio_asset_id": asset.id}

        return StageResult(keys={"audio": key}, commit=commit)

    async def _music(self, run: RenderRun) -> MusicBed | None:
        track_id = run.options.music_track_id
        if track_id is None:
            return None
        deps = self._deps
        async with deps.transaction() as session:
            track = await deps.music.require_active(session, track_id)
            asset = await deps.assets.get(session, None, track.audio_asset_id)
        path = await run.workspace.fetch(asset.storage_key, run.workspace.path(MUSIC_NAME))
        return MusicBed(path)
