from dataclasses import dataclass
from uuid import UUID

from motionile.engine.ai.graphs.deps import PipelineDependencies
from motionile.engine.ai.graphs.errors import PipelineErrorCode, pipeline_error
from motionile.engine.ai.graphs.stages import Stage
from motionile.engine.ai.graphs.state import PipelineState
from motionile.engine.ai.nodes.common import job_id_of, stage_scope
from motionile.engine.ai.ports import SceneRecord
from motionile.engine.ai.scenes.composer import ComposeError, compose
from motionile.engine.ai.scenes.models import SceneModule
from motionile.engine.ai.scenes.style_tokens import style_tokens_for
from motionile.engine.ai.storyboard import Storyboard
from motionile.engine.audio.narration_models import NarrationDocument


@dataclass(frozen=True, slots=True)
class Composition:
    storyboard: Storyboard
    narration: NarrationDocument
    records: tuple[SceneRecord, ...]
    html: str

    @property
    def fallback_ids(self) -> frozenset[str]:
        return frozenset(record.scene_id for record in self.records if record.is_fallback)


def modules_of(records: tuple[SceneRecord, ...]) -> list[SceneModule]:
    return [record.module for record in records if record.module is not None]


async def load_composition(deps: PipelineDependencies, job_id: UUID) -> Composition:
    approved = await deps.store.approved_storyboard(job_id)
    narration = await deps.store.narration(job_id)
    if approved is None or narration is None:
        raise pipeline_error(PipelineErrorCode.COMPOSITION_INVALID)
    tokens = style_tokens_for(approved.content.style_skill)
    if tokens is None:
        raise pipeline_error(PipelineErrorCode.NO_STYLE_SKILL)
    records = tuple(sorted(await deps.store.scenes(job_id), key=lambda record: record.position))
    try:
        html = compose(modules_of(records), approved.content, tokens)
    except ComposeError:
        raise pipeline_error(PipelineErrorCode.COMPOSITION_INVALID) from None
    return Composition(storyboard=approved.content, narration=narration, records=records, html=html)


async def run_compose(deps: PipelineDependencies, state: PipelineState) -> PipelineState:
    job_id = job_id_of(state)
    async with stage_scope(deps, job_id, Stage.COMPOSE):
        await load_composition(deps, job_id)
    return {}
