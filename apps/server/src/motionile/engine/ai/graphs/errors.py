from enum import StrEnum
from typing import Final

from motionile.engine.ai.guardrails.policy import POLICY_MESSAGES, PolicyCode
from motionile.engine.ai.job_options import JobStatus
from motionile.engine.ai.llm.models import LlmError, LlmErrorCode


class PipelineErrorCode(StrEnum):
    STORYBOARD_INVALID = "storyboard_invalid"
    COMPOSITION_INVALID = "composition_invalid"
    RENDER_FAILED = "render_failed"
    TTS_FAILED = "tts_failed"
    DURATION_LIMIT_EXCEEDED = "duration_limit_exceeded"
    NO_STYLE_SKILL = "no_style_skill"
    RESERVATION_LOST = "reservation_lost"


class PipelineError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class JobCancelled(Exception):  # noqa: N818
    pass


class JobEnded(Exception):  # noqa: N818
    def __init__(self, status: JobStatus) -> None:
        super().__init__(status.value)
        self.status = status


class InvalidTransitionError(Exception):
    pass


class MissingJobIdError(ValueError):
    pass


LLM_FAILURE_MESSAGES: Final[dict[LlmErrorCode, str]] = {
    LlmErrorCode.MODEL_OUTPUT_INVALID: "The AI model returned an answer Motionile could not use. Please try again.",
    LlmErrorCode.BUDGET_EXCEEDED: "This video needed more AI capacity than one video may use. Try a shorter video.",
    LlmErrorCode.LLM_UNAVAILABLE: "The AI service is unavailable right now. Please try again in a little while.",
    LlmErrorCode.LLM_TIMEOUT: "The AI service took too long to answer. Please try again in a little while.",
    LlmErrorCode.OUTPUT_BLOCKED: POLICY_MESSAGES[PolicyCode.OUTPUT_BLOCKED],
}

PIPELINE_MESSAGES: Final[dict[PipelineErrorCode, str]] = {
    PipelineErrorCode.STORYBOARD_INVALID: "Motionile could not plan a video that fits your request. Please try again.",
    PipelineErrorCode.COMPOSITION_INVALID: "Motionile could not assemble a valid video for this request.",
    PipelineErrorCode.RENDER_FAILED: "The video could not be rendered.",
    PipelineErrorCode.TTS_FAILED: "The narration could not be recorded. Please try again in a little while.",
    PipelineErrorCode.DURATION_LIMIT_EXCEEDED: "The narration is longer than the maximum video length.",
    PipelineErrorCode.NO_STYLE_SKILL: "The chosen style is not available.",
    PipelineErrorCode.RESERVATION_LOST: "The credits held for this video are no longer available, so it was stopped.",
}


def pipeline_error(code: PipelineErrorCode, suffix: str = "") -> PipelineError:
    message = PIPELINE_MESSAGES[code]
    return PipelineError(code.value, f"{message} ({suffix})" if suffix else message)


def failure_from_llm(error: LlmError) -> PipelineError:
    return PipelineError(error.code.value, LLM_FAILURE_MESSAGES[error.code])
