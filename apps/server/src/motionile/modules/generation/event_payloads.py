from collections.abc import Mapping
from typing import Final

import structlog
from pydantic import JsonValue

MAX_STRING_CHARS: Final = 500
MAX_LIST_ITEMS: Final = 50

EVENT_PAYLOAD_KEYS: Final[Mapping[str, frozenset[str]]] = {
    "job.created": frozenset({"creditsReserved"}),
    "stage.started": frozenset({"stage"}),
    "stage.completed": frozenset({"stage", "durationMs"}),
    "guard.passed": frozenset(),
    "context.ready": frozenset({"skills"}),
    "storyboard.ready": frozenset({"version", "sceneCount"}),
    "storyboard.updated": frozenset({"version", "origin"}),
    "storyboard.regenerate_requested": frozenset({"length", "digest"}),
    "critique.completed": frozenset({"revised", "blockingIssues"}),
    "approval.requested": frozenset({"version", "expiresAt"}),
    "approval.granted": frozenset({"version"}),
    "scene.voiced": frozenset({"sceneId", "durationMs"}),
    "scene.generated": frozenset({"sceneId"}),
    "scene.repaired": frozenset({"sceneId", "attempt", "issueCodes"}),
    "scene.fallback": frozenset({"sceneId", "reason"}),
    "validation.completed": frozenset({"errors", "warnings"}),
    "review.completed": frozenset({"issues"}),
    "render.progress": frozenset({"renderId", "stage", "progress"}),
    "job.cancel_requested": frozenset(),
    "job.completed": frozenset({"creditsCharged", "durationMs", "fallbackSceneIds"}),
    "job.failed": frozenset({"code", "message", "creditsReleased"}),
    "job.cancelled": frozenset({"code", "message", "creditsReleased"}),
}

logger = structlog.get_logger(__name__)


def is_scalar(value: object) -> bool:
    return value is None or isinstance(value, bool | int | float | str)


def clipped(value: JsonValue) -> JsonValue:
    return value[:MAX_STRING_CHARS] if isinstance(value, str) else value


def clean_value(value: JsonValue) -> JsonValue | None:
    if isinstance(value, list):
        if len(value) > MAX_LIST_ITEMS or not all(is_scalar(item) for item in value):
            return None
        return [clipped(item) for item in value]
    if isinstance(value, dict):
        return None
    return clipped(value)


def sanitize_payload(event_type: str, payload: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    allowed = EVENT_PAYLOAD_KEYS.get(event_type)
    if allowed is None:
        logger.warning("generation.event_type_unknown", event_type=event_type, keys=sorted(payload))
        return {}
    cleaned: dict[str, JsonValue] = {}
    dropped: list[str] = []
    for name, value in payload.items():
        kept = clean_value(value) if name in allowed else None
        if kept is None and not (name in allowed and value is None):
            dropped.append(name)
            continue
        cleaned[name] = kept
    if dropped:
        logger.warning("generation.event_payload_keys_dropped", event_type=event_type, keys=sorted(dropped))
    return cleaned
