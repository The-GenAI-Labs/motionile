from http import HTTPStatus

from motionile.core.errors import (
    AppError,
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    ValidationAppError,
)


class VoiceNotFoundError(NotFoundError):
    default_code = "voice_not_found"
    title = "Voice not found"


class VoicePreviewNotReadyError(NotFoundError):
    default_code = "voice_preview_not_ready"
    title = "Voice preview is not ready"


class VoiceNotAvailableError(ValidationAppError):
    default_code = "voice_not_available"
    title = "Voice not available"


class VoiceBusyError(ConflictError):
    default_code = "voice_busy"
    title = "The voice is still being created"


class VoiceQuotaExceededError(ConflictError):
    default_code = "voice_quota_exceeded"
    title = "Cloned voice limit reached"


class VoiceUpdateEmptyError(ValidationAppError):
    default_code = "voice_update_empty"
    title = "Nothing to update"


class VoiceProviderUnavailableError(AppError):
    status_code = HTTPStatus.BAD_GATEWAY
    default_code = "voice_provider_unavailable"
    title = "The voice provider is unavailable"


class VoicePreviewFailedError(AppError):
    status_code = HTTPStatus.BAD_GATEWAY
    default_code = "voice_preview_failed"
    title = "The voice preview could not be generated"


class ConsentStatementOutdatedError(ConflictError):
    default_code = "consent_statement_outdated"
    title = "The consent statement has changed"


class CloneAttemptNotFoundError(NotFoundError):
    default_code = "clone_attempt_not_found"
    title = "Clone attempt not found"


class CloneAttemptBusyError(ConflictError):
    default_code = "clone_attempt_busy"
    title = "The clone attempt is busy"


class CloneSampleNotFoundError(NotFoundError):
    default_code = "clone_sample_not_found"
    title = "Sample not found"


class ConsentRecordingMissingError(ValidationAppError):
    default_code = "consent_recording_missing"
    title = "The consent recording is missing"


class SamplesTooShortError(ValidationAppError):
    default_code = "samples_too_short"
    title = "The samples are too short"


class SamplesTooLongError(ValidationAppError):
    default_code = "samples_too_long"
    title = "The samples are too long"


class TooManySamplesError(ValidationAppError):
    default_code = "too_many_samples"
    title = "Too many sample files"


class AudioNotAudioError(ValidationAppError):
    default_code = "audio_not_audio"
    title = "The file is not audio"


class AudioTooLargeError(PayloadTooLargeError):
    default_code = "audio_too_large"
    title = "The audio file is too large"


class AudioTooShortError(ValidationAppError):
    default_code = "audio_too_short"
    title = "The audio is too short"


class AudioTooLongError(ValidationAppError):
    default_code = "audio_too_long"
    title = "The audio is too long"


class AudioVideoStreamPresentError(ValidationAppError):
    default_code = "audio_video_stream_present"
    title = "The file carries a video stream"


class AudioUnsupportedFormatError(ValidationAppError):
    default_code = "audio_unsupported_format"
    title = "Unsupported audio format"


class AudioProbeFailedError(ValidationAppError):
    default_code = "audio_probe_failed"
    title = "The audio could not be read"
