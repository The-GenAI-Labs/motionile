from motionile.engine.ai.graphs.deps import PipelineDependencies
from motionile.engine.ai.graphs.errors import PipelineErrorCode, pipeline_error
from motionile.engine.ai.graphs.events import EventType, emit
from motionile.engine.ai.graphs.stages import Stage
from motionile.engine.ai.graphs.state import PipelineState
from motionile.engine.ai.nodes.common import job_id_of, require_reservation, stage_scope
from motionile.engine.ai.ports import JobSnapshot, NarrationScript, StoredStoryboard
from motionile.engine.audio.narration import NarrationError
from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.audio.providers.base import ProviderError
from motionile.engine.audio.synthesis import EmptyNarrationTextError


def scripts_for(storyboard: StoredStoryboard) -> list[NarrationScript]:
    return [NarrationScript(scene_id=scene.id, text=scene.narration) for scene in storyboard.content.scenes]


def covers(narration: NarrationDocument, scripts: list[NarrationScript]) -> bool:
    return [scene.id for scene in narration.scenes] == [script.scene_id for script in scripts]


async def synthesize(deps: PipelineDependencies, job: JobSnapshot, scripts: list[NarrationScript]) -> NarrationDocument:
    try:
        return await deps.narrator.narrate(job, scripts)
    except (NarrationError, EmptyNarrationTextError):
        raise pipeline_error(PipelineErrorCode.TTS_FAILED) from None
    except ProviderError as error:
        if error.retryable:
            raise
        raise pipeline_error(PipelineErrorCode.TTS_FAILED, error.code) from None


async def run_voice(deps: PipelineDependencies, state: PipelineState) -> PipelineState:
    job_id = job_id_of(state)
    async with stage_scope(deps, job_id, Stage.VOICE):
        job = await deps.store.snapshot(job_id)
        approved = await deps.store.approved_storyboard(job_id)
        if approved is None:
            raise pipeline_error(PipelineErrorCode.STORYBOARD_INVALID)
        scripts = scripts_for(approved)
        existing = await deps.store.narration(job_id)
        if existing is not None and covers(existing, scripts):
            return {}
        await require_reservation(deps, job)
        narration = await synthesize(deps, job, scripts)
        if narration.total_duration_ms > deps.config.max_duration_ms:
            raise pipeline_error(PipelineErrorCode.DURATION_LIMIT_EXCEEDED)
        await deps.store.save_narration(job_id, narration)
        for scene in narration.scenes:
            payload = {"sceneId": scene.id, "durationMs": scene.duration_ms}
            await emit(deps, job_id, EventType.SCENE_VOICED, Stage.VOICE, payload)
        return {}
