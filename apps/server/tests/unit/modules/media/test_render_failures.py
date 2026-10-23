import pytest

from motionile.engine.audio.mix import MixError
from motionile.engine.audio.narration import NarrationError
from motionile.engine.audio.providers.base import (
    ProviderAuthenticationError,
    ProviderRateLimitedError,
    ProviderRejectedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from motionile.engine.audio.synthesis import EmptyNarrationTextError
from motionile.engine.ffmpeg import FfmpegError
from motionile.engine.render.models import (
    BrowserCrashError,
    DurationLimitError,
    InsufficientDiskError,
    InvalidCompositionError,
    IssueCode,
    NetworkViolationError,
    OutputCheckError,
    PageError,
    SandboxTimeoutError,
    make_issue,
)
from motionile.modules.media.domain import RenderFailureCode
from motionile.modules.media.exceptions import MusicTrackUnavailableError
from motionile.modules.media.pipeline import RenderFailedError, classify

CASES: list[tuple[Exception, RenderFailureCode]] = [
    (InvalidCompositionError([make_issue(IssueCode.FORBIDDEN_URL, "x")]), RenderFailureCode.INVALID_COMPOSITION),
    (NetworkViolationError(["https://evil.example"]), RenderFailureCode.NETWORK_VIOLATION),
    (SandboxTimeoutError("slow"), RenderFailureCode.TIMEOUT),
    (PageError(["boom"]), RenderFailureCode.PAGE_ERROR),
    (BrowserCrashError("gone"), RenderFailureCode.BROWSER_CRASH),
    (DurationLimitError("too long"), RenderFailureCode.DURATION_LIMIT_EXCEEDED),
    (InsufficientDiskError("C:/secret/path"), RenderFailureCode.INSUFFICIENT_DISK),
    (OutputCheckError(["codec"]), RenderFailureCode.OUTPUT_CHECK_FAILED),
    (ProviderRejectedError("provider said no", status_code=400), RenderFailureCode.TTS_FAILED),
    (ProviderAuthenticationError("bad key"), RenderFailureCode.TTS_FAILED),
    (EmptyNarrationTextError("empty"), RenderFailureCode.TTS_FAILED),
    (NarrationError("scene has no audio"), RenderFailureCode.TTS_FAILED),
    (MixError("loudness"), RenderFailureCode.OUTPUT_CHECK_FAILED),
    (MusicTrackUnavailableError(), RenderFailureCode.MUSIC_TRACK_UNAVAILABLE),
]


@pytest.mark.parametrize(("error", "code"), CASES)
def test_deterministic_errors_map_to_stable_codes(error: Exception, code: RenderFailureCode) -> None:
    failure = classify(error)

    assert failure is not None
    assert failure.code is code


@pytest.mark.parametrize(
    "error",
    [
        ProviderUnavailableError("down"),
        ProviderTimeoutError("slow"),
        ProviderRateLimitedError("limited"),
        FfmpegError("crashed"),
        ConnectionError("storage"),
        OSError("disk"),
        TimeoutError(),
        RuntimeError("bug"),
    ],
)
def test_infrastructure_errors_are_left_to_the_task_retry(error: Exception) -> None:
    assert classify(error) is None


@pytest.mark.parametrize(("error", "code"), CASES)
def test_messages_never_leak_internals(error: Exception, code: RenderFailureCode) -> None:
    del code
    failure = classify(error)

    assert failure is not None
    for forbidden in ("evil.example", "C:/secret", "provider said no", "bad key", "Traceback", "/usr/"):
        assert forbidden not in failure.message
    assert len(failure.message) <= 500


def test_a_sandbox_failure_carries_the_issue_for_the_report() -> None:
    failure = classify(NetworkViolationError(["https://evil.example"]))

    assert failure is not None
    assert [issue.code for issue in failure.issues] == ["network_violation"]


def test_an_explicit_failure_passes_through() -> None:
    explicit = RenderFailedError(RenderFailureCode.VALIDATION_FAILED, "no")

    assert classify(explicit) is explicit
