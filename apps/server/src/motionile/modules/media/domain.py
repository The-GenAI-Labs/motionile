from collections.abc import Mapping
from enum import StrEnum


class AssetKind(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    SUBTITLE = "subtitle"
    THUMBNAIL = "thumbnail"
    VOICE_SAMPLE = "voice_sample"
    SKILL_FILE = "skill_file"
    AVATAR = "avatar"
    HTML = "html"


class AssetStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class Aspect(StrEnum):
    LANDSCAPE = "16:9"
    PORTRAIT = "9:16"
    SQUARE = "1:1"

    @property
    def slug(self) -> str:
        return self.value.replace(":", "x")


class RenderSource(StrEnum):
    TESTBED = "testbed"
    JOB = "job"
    MCP = "mcp"


class RenderStatus(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    VOICING = "voicing"
    MIXING = "mixing"
    CAPTURING = "capturing"
    ENCODING = "encoding"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RenderStage(StrEnum):
    PREPARING = "preparing"
    VOICING = "voicing"
    MIXING = "mixing"
    CAPTURING = "capturing"
    ENCODING = "encoding"
    FINALIZING = "finalizing"

    @property
    def status(self) -> RenderStatus:
        return RenderStatus(self.value)


class RenditionStatus(StrEnum):
    PENDING = "pending"
    RENDERING = "rendering"
    READY = "ready"
    FAILED = "failed"


class TtsProvider(StrEnum):
    ELEVENLABS = "elevenlabs"
    OPENAI = "openai"
    FAKE = "fake"


class RenderFailureCode(StrEnum):
    INVALID_COMPOSITION = "invalid_composition"
    UNSUPPORTED_COMPOSITION = "unsupported_composition"
    VALIDATION_FAILED = "validation_failed"
    NETWORK_VIOLATION = "network_violation"
    TIMEOUT = "timeout"
    PAGE_ERROR = "page_error"
    BROWSER_CRASH = "browser_crash"
    DURATION_LIMIT_EXCEEDED = "duration_limit_exceeded"
    INSUFFICIENT_DISK = "insufficient_disk"
    TTS_FAILED = "tts_failed"
    OUTPUT_CHECK_FAILED = "output_check_failed"
    MUSIC_TRACK_UNAVAILABLE = "music_track_unavailable"
    RENDER_STALLED = "render_stalled"


RENDER_PIPELINE: tuple[RenderStage, ...] = (
    RenderStage.PREPARING,
    RenderStage.VOICING,
    RenderStage.MIXING,
    RenderStage.CAPTURING,
    RenderStage.ENCODING,
    RenderStage.FINALIZING,
)

STAGE_PROGRESS_WEIGHTS: Mapping[RenderStage, int] = {
    RenderStage.PREPARING: 5,
    RenderStage.VOICING: 15,
    RenderStage.MIXING: 10,
    RenderStage.CAPTURING: 55,
    RenderStage.ENCODING: 10,
    RenderStage.FINALIZING: 5,
}

TERMINAL_RENDER_STATUSES: frozenset[RenderStatus] = frozenset(
    {RenderStatus.COMPLETED, RenderStatus.FAILED, RenderStatus.CANCELLED}
)
ACTIVE_RENDER_STATUSES: frozenset[RenderStatus] = frozenset(set(RenderStatus) - TERMINAL_RENDER_STATUSES)

RENDER_TRANSITIONS: Mapping[RenderStatus, frozenset[RenderStatus]] = {
    RenderStatus.QUEUED: frozenset({RenderStatus.PREPARING, RenderStatus.CANCELLED, RenderStatus.FAILED}),
    RenderStatus.PREPARING: frozenset({RenderStatus.VOICING, RenderStatus.CANCELLED, RenderStatus.FAILED}),
    RenderStatus.VOICING: frozenset({RenderStatus.MIXING, RenderStatus.CANCELLED, RenderStatus.FAILED}),
    RenderStatus.MIXING: frozenset({RenderStatus.CAPTURING, RenderStatus.CANCELLED, RenderStatus.FAILED}),
    RenderStatus.CAPTURING: frozenset({RenderStatus.ENCODING, RenderStatus.CANCELLED, RenderStatus.FAILED}),
    RenderStatus.ENCODING: frozenset({RenderStatus.FINALIZING, RenderStatus.CANCELLED, RenderStatus.FAILED}),
    RenderStatus.FINALIZING: frozenset({RenderStatus.COMPLETED, RenderStatus.CANCELLED, RenderStatus.FAILED}),
    RenderStatus.COMPLETED: frozenset(),
    RenderStatus.FAILED: frozenset(),
    RenderStatus.CANCELLED: frozenset(),
}

INITIAL_RENDER_STATUS = RenderStatus.QUEUED


class InvalidRenderTransitionError(Exception):
    def __init__(self, current: RenderStatus, target: RenderStatus) -> None:
        super().__init__(f"renders.status cannot move from {current.value} to {target.value}")
        self.current = current
        self.target = target


def can_transition(current: RenderStatus, target: RenderStatus) -> bool:
    return target in RENDER_TRANSITIONS[current]


def require_transition(current: RenderStatus, target: RenderStatus) -> None:
    if not can_transition(current, target):
        raise InvalidRenderTransitionError(current, target)


def is_terminal(status: RenderStatus) -> bool:
    return status in TERMINAL_RENDER_STATUSES


def following_status(status: RenderStatus) -> RenderStatus | None:
    if status is RenderStatus.QUEUED:
        return RenderStatus.PREPARING
    if status is RenderStatus.FINALIZING:
        return RenderStatus.COMPLETED
    stage_names = [stage.status for stage in RENDER_PIPELINE]
    if status not in stage_names:
        return None
    return stage_names[stage_names.index(status) + 1]
