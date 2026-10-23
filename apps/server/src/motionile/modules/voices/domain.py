from datetime import timedelta
from enum import StrEnum


class VoiceKind(StrEnum):
    BUILTIN = "builtin"
    CLONED = "cloned"


class VoiceStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    DISABLED = "disabled"


class VoiceProvider(StrEnum):
    ELEVENLABS = "elevenlabs"
    OPENAI = "openai"
    FAKE = "fake"


class VoiceFailureCode(StrEnum):
    CONSENT_MISMATCH = "consent_mismatch"
    SAMPLE_INVALID = "sample_invalid"
    PROVIDER_FAILED = "provider_failed"
    PREVIEW_FAILED = "preview_failed"
    TRANSCRIPTION_FAILED = "transcription_failed"
    ATTEMPT_EXPIRED = "attempt_expired"
    CLONE_STALLED = "clone_stalled"
    CREDIT_RESERVATION_EXPIRED = "credit_reservation_expired"


STALLED_CLONE_AGE = timedelta(hours=2)
CLONE_MAX_ATTEMPTS = 5
CLONE_RETRY_WAIT_SECONDS = 10
CLONE_RETRY_EXPONENTIAL_WAIT = 10
CLONE_RESERVATION_MARGIN = timedelta(hours=6)


def clone_retry_window() -> timedelta:
    seconds = sum(
        CLONE_RETRY_WAIT_SECONDS + CLONE_RETRY_EXPONENTIAL_WAIT ** (attempt + 1)
        for attempt in range(CLONE_MAX_ATTEMPTS - 1)
    )
    return timedelta(seconds=seconds)


def clone_reservation_ttl() -> timedelta:
    return STALLED_CLONE_AGE + clone_retry_window() + CLONE_RESERVATION_MARGIN
