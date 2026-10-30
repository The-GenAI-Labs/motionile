from collections.abc import Sequence

from motionile.core.errors import ConflictError, NotFoundError, ServiceUnavailableError, ValidationAppError


class PromptNotActiveError(ServiceUnavailableError):
    default_code = "prompt_not_active"
    title = "The prompt is not active"

    def __init__(self, key: str) -> None:
        super().__init__(f"The prompt {key} has no active version.")
        self.key = key


class PromptTemplateNotFoundError(NotFoundError):
    default_code = "prompt_template_not_found"
    title = "Prompt template not found"


class PromptVersionNotFoundError(NotFoundError):
    default_code = "prompt_version_not_found"
    title = "Prompt version not found"


class EvalRunNotFoundError(NotFoundError):
    default_code = "eval_run_not_found"
    title = "Evaluation run not found"


class DraftInvalidError(ValidationAppError):
    default_code = "prompt_draft_invalid"
    title = "The prompt draft is invalid"


class DraftExistsError(ConflictError):
    default_code = "prompt_version_exists"
    title = "A version with this text already exists"


class ActivationBlockedError(ConflictError):
    default_code = "activation_blocked"
    title = "The version cannot be activated yet"

    def __init__(self, missing: Sequence[str], failed: Sequence[str]) -> None:
        super().__init__(
            "Every required suite needs a finished, passing run that covers this version.",
            extensions={"missingSuites": ",".join(missing), "failedSuites": ",".join(failed)},
        )
        self.missing = tuple(missing)
        self.failed = tuple(failed)


class ActivationConflictError(ConflictError):
    default_code = "activation_conflict"
    title = "The active version changed while this request ran"


class NoPreviousVersionError(ConflictError):
    default_code = "no_previous_version"
    title = "There is no earlier version to roll back to"


class UnknownSuiteError(ValidationAppError):
    default_code = "unknown_suite"
    title = "Unknown evaluation suite"


class EvalRunInvalidError(ValidationAppError):
    default_code = "eval_run_invalid"
    title = "The evaluation run is invalid"


class BootstrapRefusedError(Exception):
    pass
