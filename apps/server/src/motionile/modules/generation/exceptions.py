from http import HTTPStatus

from motionile.core.errors import AppError, ConflictError, FieldError, NotFoundError, ValidationAppError
from motionile.engine.ai.guardrails import PolicyCode, policy_message


class JobNotFoundError(NotFoundError):
    default_code = "job_not_found"
    title = "Job not found"


class TopicNotFoundError(NotFoundError):
    default_code = "topic_not_found"
    title = "Topic not found"


class TooManyActiveJobsError(ConflictError):
    default_code = "too_many_active_jobs"
    title = "Too many active jobs"

    def __init__(self, limit: int) -> None:
        super().__init__(
            "Wait for a running video to finish or cancel it before starting another.",
            extensions={"limit": limit},
        )


class JobInsufficientCreditsError(AppError):
    status_code = HTTPStatus.PAYMENT_REQUIRED
    default_code = "insufficient_credits"
    title = "Insufficient credits"

    def __init__(self, *, available: int, required: int) -> None:
        super().__init__(
            "The wallet does not hold enough available credits for this video.",
            extensions={"available": available, "required": required, "shortfall": max(0, required - available)},
        )


class StoryboardNotEditableError(ConflictError):
    default_code = "storyboard_not_editable"
    title = "Storyboard not editable"


class StoryboardNotFoundError(NotFoundError):
    default_code = "storyboard_not_found"
    title = "Storyboard not found"


class StoryboardVersionConflictError(ConflictError):
    default_code = "storyboard_version_conflict"
    title = "Storyboard version conflict"

    def __init__(self, current_version: int) -> None:
        super().__init__(
            "The storyboard changed since you loaded it. Reload it and apply your edit again.",
            extensions={"currentVersion": current_version},
        )


class StoryboardInvalidError(ValidationAppError):
    default_code = "storyboard_invalid"
    title = "Storyboard invalid"

    def __init__(self, errors: list[FieldError]) -> None:
        super().__init__("The storyboard has problems that must be fixed before it can be saved.", errors=errors)


class JobNotCancellableError(ConflictError):
    default_code = "job_not_cancellable"
    title = "Job cannot be cancelled"


class JobNotDeletableError(ConflictError):
    default_code = "job_not_deletable"
    title = "Job cannot be deleted"


class JobNotRevisableError(ConflictError):
    default_code = "job_not_revisable"
    title = "Job cannot be revised"


class InputRefusedError(ValidationAppError):
    default_code = "input_refused"
    title = "Request not supported"

    def __init__(self, policy: PolicyCode) -> None:
        super().__init__(policy_message(policy), extensions={"policy": policy.value})
        self.policy = policy


class StyleNotFoundError(ValidationAppError):
    default_code = "style_not_found"
    title = "Style not found"


class LanguageNotSupportedError(ValidationAppError):
    default_code = "language_not_supported"
    title = "Language not supported"


class AspectNotAllowedError(ValidationAppError):
    default_code = "aspect_not_allowed"
    title = "Aspect not allowed"


class JobOptionsInvalidError(ValidationAppError):
    default_code = "job_options_invalid"
    title = "Job options invalid"


class PipelineNotWiredError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("the pipeline runner is not wired")


class ShareNotFoundError(NotFoundError):
    default_code = "share_not_found"
    title = "Share link not found"


class ShareRenditionNotFoundError(NotFoundError):
    default_code = "share_rendition_not_found"
    title = "Rendition not found"


class JobNotShareableError(ConflictError):
    default_code = "job_not_shareable"
    title = "Job cannot be shared"
