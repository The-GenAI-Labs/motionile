from motionile.modules.media.domain import RenderStage
from motionile.modules.media.pipeline.context import PipelineDeps, Stage
from motionile.modules.media.pipeline.stages.capturing import CapturingStage
from motionile.modules.media.pipeline.stages.encoding import EncodingStage
from motionile.modules.media.pipeline.stages.finalizing import FinalizingStage
from motionile.modules.media.pipeline.stages.mixing import MixingStage
from motionile.modules.media.pipeline.stages.prepare import PrepareStage
from motionile.modules.media.pipeline.stages.voicing import VoicingStage


def build_stages(deps: PipelineDeps) -> dict[RenderStage, Stage]:
    stages: list[Stage] = [
        PrepareStage(deps),
        VoicingStage(deps),
        MixingStage(deps),
        CapturingStage(deps),
        EncodingStage(deps),
        FinalizingStage(deps),
    ]
    return {stage.stage: stage for stage in stages}


__all__ = ["build_stages"]
