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
