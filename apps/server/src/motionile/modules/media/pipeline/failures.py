from collections.abc import Iterable

import structlog

from motionile.engine.audio.mix import MixError
from motionile.engine.audio.narration import NarrationError
from motionile.engine.audio.providers.base import ProviderError
from motionile.engine.audio.synthesis import EmptyNarrationTextError
from motionile.engine.render.models import (
    BrowserCrashError,
    DurationLimitError,
    InsufficientDiskError,
    InvalidCompositionError,
    NetworkViolationError,
    OutputCheckError,
    PageError,
    SandboxError,
    SandboxTimeoutError,
    ValidationIssue,
    ValidationReport,
    issue_from_error,
)
from motionile.modules.media.domain import RenderFailureCode
from motionile.modules.media.exceptions import MusicTrackUnavailableError

MAX_MESSAGE_CHARS = 500
MAX_LISTED_CODES = 8

logger = structlog.get_logger(__name__)


class RenderFailedError(Exception):
    def __init__(
        self,
        code: RenderFailureCode,
        message: str,
        *,
        issues: Iterable[ValidationIssue] = (),
        report: ValidationReport | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message[:MAX_MESSAGE_CHARS]
        self.issues = tuple(issues)
        self.report = report


class RenderStateChangedError(Exception):
    pass


def listed(codes: Iterable[str]) -> str:
    unique = sorted(set(codes))
    shown = ", ".join(unique[:MAX_LISTED_CODES])
    return shown + (", ..." if len(unique) > MAX_LISTED_CODES else "")


def sandbox_failure(error: SandboxError) -> RenderFailedError | None:
    issue = issue_from_error(error)
    if isinstance(error, NetworkViolationError):
        message = "The composition tried to reach a resource outside the render sandbox."
        return RenderFailedError(RenderFailureCode.NETWORK_VIOLATION, message, issues=[issue])
    if isinstance(error, SandboxTimeoutError):
        message = "The composition did not finish loading or rendering in time."
        return RenderFailedError(RenderFailureCode.TIMEOUT, message, issues=[issue])
    if isinstance(error, PageError):
        return RenderFailedError(
            RenderFailureCode.PAGE_ERROR, "The composition raised an error while rendering.", issues=[issue]
        )
    if isinstance(error, BrowserCrashError):
        return RenderFailedError(
            RenderFailureCode.BROWSER_CRASH, "The browser crashed while rendering.", issues=[issue]
        )
    return None


def provider_failure(error: ProviderError) -> RenderFailedError | None:
    if error.retryable:
        return None
    logger.warning("media.render_tts_rejected", provider_error=error.code, status=error.status_code)
    return RenderFailedError(RenderFailureCode.TTS_FAILED, "The speech provider could not synthesize the narration.")


FIXED_FAILURES: tuple[tuple[type[Exception], RenderFailureCode, str], ...] = (
    (
        InsufficientDiskError,
        RenderFailureCode.INSUFFICIENT_DISK,
        "The render worker does not have enough free disk space.",
    ),
    (EmptyNarrationTextError, RenderFailureCode.TTS_FAILED, "A scene has no text to speak."),
    (NarrationError, RenderFailureCode.TTS_FAILED, "The narration could not be assembled from the scenes."),
    (MixError, RenderFailureCode.OUTPUT_CHECK_FAILED, "The audio could not be mixed."),
    (
        MusicTrackUnavailableError,
        RenderFailureCode.MUSIC_TRACK_UNAVAILABLE,
        "The selected music track is not available.",
    ),
)


def described_failure(error: BaseException) -> RenderFailedError | None:
    if isinstance(error, InvalidCompositionError):
        message = f"The composition failed the static checks: {listed(issue.code for issue in error.issues)}."
        return RenderFailedError(RenderFailureCode.INVALID_COMPOSITION, message, issues=error.issues)
    if isinstance(error, DurationLimitError):
        return RenderFailedError(RenderFailureCode.DURATION_LIMIT_EXCEEDED, error.message)
    if isinstance(error, OutputCheckError):
        return RenderFailedError(
            RenderFailureCode.OUTPUT_CHECK_FAILED, f"The rendered video failed verification: {error.message}"
        )
    return None


def classify(error: BaseException) -> RenderFailedError | None:
    if isinstance(error, RenderFailedError):
        return error
    if isinstance(error, SandboxError):
        return sandbox_failure(error)
    if isinstance(error, ProviderError):
        return provider_failure(error)
    for kind, code, message in FIXED_FAILURES:
        if isinstance(error, kind):
            return RenderFailedError(code, message)
    return described_failure(error)
