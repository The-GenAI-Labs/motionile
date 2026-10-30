from enum import StrEnum
from typing import Final

from motionile.engine.ai.job_options import JobStatus


class Stage(StrEnum):
    GUARD = "guard"
    CONTEXT = "context"
    PLAN = "plan"
    CRITIQUE = "critique"
    APPROVAL = "approval"
    DECISION = "decision"
    VOICE = "voice"
    SCENES = "scenes"
    COMPOSE = "compose"
    VALIDATE = "validate"
    VISUAL_REVIEW = "visual_review"
    REPAIR = "repair"
    RENDER = "render"
    FINALIZE = "finalize"


STAGE_STATUS: Final[dict[Stage, JobStatus]] = {
    Stage.GUARD: JobStatus.PLANNING,
    Stage.CONTEXT: JobStatus.PLANNING,
    Stage.PLAN: JobStatus.PLANNING,
    Stage.CRITIQUE: JobStatus.PLANNING,
    Stage.APPROVAL: JobStatus.PLANNING,
    Stage.DECISION: JobStatus.AWAITING_APPROVAL,
    Stage.VOICE: JobStatus.VOICING,
    Stage.SCENES: JobStatus.GENERATING,
    Stage.COMPOSE: JobStatus.GENERATING,
    Stage.VALIDATE: JobStatus.VALIDATING,
    Stage.VISUAL_REVIEW: JobStatus.VALIDATING,
    Stage.REPAIR: JobStatus.GENERATING,
    Stage.RENDER: JobStatus.RENDERING,
    Stage.FINALIZE: JobStatus.RENDERING,
}
