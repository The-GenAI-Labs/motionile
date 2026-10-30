from enum import StrEnum


class CallMetadataKey(StrEnum):
    FIXTURE = "fixture"
    SCENE_ID = "sceneId"
    TOPIC = "topic"
    DURATION_MS = "durationMs"
    ASPECTS = "aspects"
    LANGUAGE = "language"
    STYLE = "style"


ASPECT_SEPARATOR = ","


def join_aspects(aspects: list[str]) -> str:
    return ASPECT_SEPARATOR.join(aspects)


def split_aspects(value: str) -> list[str]:
    return [part.strip() for part in value.split(ASPECT_SEPARATOR) if part.strip()]
