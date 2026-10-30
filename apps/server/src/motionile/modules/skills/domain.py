from enum import StrEnum
from typing import Final

AUDIT_TARGET: Final = "skill"
CHECKSUM_PREFIX_LENGTH: Final = 12


class SkillAction(StrEnum):
    CREATED = "skills.created"
    VERSION_ADDED = "skills.version_added"
    RESEEDED = "skills.reseeded"


class EmbeddingStatus(StrEnum):
    READY = "ready"
    STALE = "stale"
    MISSING = "missing"


def checksum_prefix(checksum: bytes) -> str:
    return checksum.hex()[:CHECKSUM_PREFIX_LENGTH]


def embedding_status(stored_model: str | None, expected_model: str) -> EmbeddingStatus:
    if stored_model is None:
        return EmbeddingStatus.MISSING
    return EmbeddingStatus.READY if stored_model == expected_model else EmbeddingStatus.STALE
