import re
import secrets
from typing import Final

SLUG_PATTERN: Final = re.compile(r"^[A-Za-z0-9_-]{10,32}$")
SLUG_ENTROPY_BYTES: Final = 16
UNKNOWN_SLUG: Final = "x" * 22


def new_slug() -> str:
    return secrets.token_urlsafe(SLUG_ENTROPY_BYTES)


def is_valid_slug(value: str) -> bool:
    return SLUG_PATTERN.fullmatch(value) is not None


def lookup_slug(value: str) -> str:
    return value if is_valid_slug(value) else UNKNOWN_SLUG
