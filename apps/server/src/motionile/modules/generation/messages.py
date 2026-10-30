from dataclasses import dataclass
from typing import Final

from motionile.engine.ai.guardrails import POLICY_MESSAGES, PolicyCode, is_refusal_code
from motionile.engine.ai.llm.models import LlmErrorCode
from motionile.modules.media import RenderFailureCode

POLICY_TITLE: Final = "This request cannot be made into a video"
GENERIC_TITLE: Final = "The video could not be completed"
GENERIC_MESSAGE: Final = "Something went wrong while making your video. Your credits were returned. Try again."
RENDER_TITLE: Final = "The video could not be rendered"
RENDER_MESSAGE: Final = "The video could not be rendered. Your credits were returned. Try again in a moment."


@dataclass(frozen=True, slots=True)
class ErrorDescription:
    title: str
    message: str


KNOWN_FAILURES: Final[dict[str, ErrorDescription]] = {
    LlmErrorCode.MODEL_OUTPUT_INVALID.value: ErrorDescription(
        "The video could not be planned",
        "The planner returned something Motionile could not use. Your credits were returned. Try again.",
    ),
    LlmErrorCode.BUDGET_EXCEEDED.value: ErrorDescription(
        "This video needed too much work",
        "The video was more complex than Motionile can make in one go. Your credits were returned. "
        "Try a shorter or simpler topic.",
    ),
    LlmErrorCode.LLM_UNAVAILABLE.value: ErrorDescription(
        "Motionile is busy",
        "The writing service is unavailable right now. Your credits were returned. Try again in a few minutes.",
    ),
    LlmErrorCode.LLM_TIMEOUT.value: ErrorDescription(
        "Motionile is busy",
        "The writing service took too long to answer. Your credits were returned. Try again in a few minutes.",
    ),
    LlmErrorCode.OUTPUT_BLOCKED.value: ErrorDescription(POLICY_TITLE, POLICY_MESSAGES[PolicyCode.OUTPUT_BLOCKED]),
    "no_style_skill": ErrorDescription(
        "The style is unavailable",
        "The style you picked is not available any more. Your credits were returned. Pick another style.",
    ),
    "tts_failed": ErrorDescription(
        "The narration could not be recorded",
        "The voice service failed to record the narration. Your credits were returned. "
        "Try again or pick another voice.",
    ),
    "composition_invalid": ErrorDescription(
        "The video could not be assembled",
        "Motionile could not assemble the scenes into a valid video. Your credits were returned. Try again.",
    ),
    "reservation_lost": ErrorDescription(
        "The video was stopped",
        "The credits held for this video were no longer available, so Motionile stopped before spending more. "
        "Try again.",
    ),
    "job_stalled": ErrorDescription(
        "The video took too long",
        "The video stopped making progress and was cancelled. Your credits were returned. Try again.",
    ),
    "approval_expired": ErrorDescription(
        "The storyboard was not approved in time",
        "The storyboard waited too long for your approval. Your credits were returned.",
    ),
}
RENDER_FAILURES: Final[dict[str, ErrorDescription]] = {
    code.value: ErrorDescription(RENDER_TITLE, RENDER_MESSAGE) for code in RenderFailureCode
}


def describe_error(code: str | None, stored_message: str | None) -> ErrorDescription | None:
    if code is None:
        return None
    if is_refusal_code(code):
        return ErrorDescription(POLICY_TITLE, POLICY_MESSAGES[PolicyCode(code)])
    known = KNOWN_FAILURES.get(code) or RENDER_FAILURES.get(code)
    if known is not None:
        return known
    return ErrorDescription(GENERIC_TITLE, stored_message or GENERIC_MESSAGE)
