from motionile.core.errors import (
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    RateLimitedError,
    ServiceUnavailableError,
    ValidationAppError,
)


class RenderNotFoundError(NotFoundError):
    default_code = "render_not_found"
    title = "Render not found"


class RenderNotFinishedError(ConflictError):
    default_code = "render_not_finished"
    title = "Render not finished"


class AssetNotFoundError(NotFoundError):
    default_code = "asset_not_found"
    title = "Asset not found"


class AssetKeyExistsError(ConflictError):
    default_code = "asset_key_exists"
    title = "Asset already exists"


class AssetInUseError(ConflictError):
    default_code = "asset_in_use"
    title = "Asset is in use"


class AssetTooLargeError(PayloadTooLargeError):
    default_code = "asset_too_large"
    title = "Asset too large"


class MediaKeyNotSignableError(ValidationAppError):
    default_code = "media_key_not_signable"
    title = "Media key cannot be signed"


class MediaDeliveryMisconfiguredError(ServiceUnavailableError):
    default_code = "media_delivery_misconfigured"
    title = "Media delivery is not configured"


class MusicTrackNotFoundError(NotFoundError):
    default_code = "music_track_not_found"
    title = "Music track not found"


class MusicTrackUnavailableError(ValidationAppError):
    default_code = "music_track_unavailable"
    title = "Music track unavailable"


class MusicUpdateEmptyError(ValidationAppError):
    default_code = "music_update_empty"
    title = "Nothing to update"


class MusicNotAudioError(ValidationAppError):
    default_code = "music_not_audio"
    title = "The file is not audio"


class MusicTooLargeError(PayloadTooLargeError):
    default_code = "music_too_large"
    title = "The audio file is too large"


class MusicTooShortError(ValidationAppError):
    default_code = "music_too_short"
    title = "The audio is too short"


class MusicTooLongError(ValidationAppError):
    default_code = "music_too_long"
    title = "The audio is too long"


class MusicVideoStreamError(ValidationAppError):
    default_code = "music_video_stream"
    title = "The file carries a video stream"


class MusicUnsupportedFormatError(ValidationAppError):
    default_code = "music_unsupported_format"
    title = "Unsupported audio format"


class MusicUnreadableError(ValidationAppError):
    default_code = "music_unreadable"
    title = "The audio could not be read"


class MusicTranscodeFailedError(ValidationAppError):
    default_code = "music_transcode_failed"
    title = "The audio could not be converted"


class RenderOptionsInvalidError(ValidationAppError):
    default_code = "render_options_invalid"
    title = "Render options are invalid"


class CompositionTooLargeError(PayloadTooLargeError):
    default_code = "composition_too_large"
    title = "The composition is too large"


class RenderUploadTooLargeError(PayloadTooLargeError):
    default_code = "render_upload_too_large"
    title = "The upload is too large"


class RenderAudioRejectedError(ValidationAppError):
    default_code = "render_audio_rejected"
    title = "The uploaded audio was rejected"


class GoldenNotFoundError(NotFoundError):
    default_code = "golden_not_found"
    title = "Golden composition not found"


class AssetKeyTakenError(Exception):
    pass


class AssetReferencedError(Exception):
    pass


class TooManyStreamsError(RateLimitedError):
    default_code = "too_many_streams"
    title = "Too many open progress streams"
