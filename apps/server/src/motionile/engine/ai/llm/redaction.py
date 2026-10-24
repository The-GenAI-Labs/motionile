import re
from typing import Final, cast

REDACTED: Final = "[redacted]"
TRACE_TEXT_LIMIT: Final = 4_000

BEARER_PATTERN: Final = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
JWT_PATTERN: Final = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
VENDOR_KEY_PATTERN: Final = re.compile(
    r"\b(?:(?:sk|pk|rk)-[A-Za-z0-9][A-Za-z0-9_-]{15,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})"
)
SECRET_ASSIGNMENT_PATTERN: Final = re.compile(
    r"""(?i)\b(api[_-]?key|secret|token|password|passwd|authorization)\b(["']?\s*[:=]\s*["']?)[^\s"',}]{4,}"""
)
EMAIL_PATTERN: Final = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
PHONE_PATTERN: Final = re.compile(r"(?<![\w-])\+?\(?\d(?:[\s().-]{0,2}\d){9,14}(?![\w-])")


def redact(text: str) -> str:
    redacted = BEARER_PATTERN.sub(f"Bearer {REDACTED}", text)
    redacted = JWT_PATTERN.sub(REDACTED, redacted)
    redacted = VENDOR_KEY_PATTERN.sub(REDACTED, redacted)
    redacted = SECRET_ASSIGNMENT_PATTERN.sub(rf"\1\2{REDACTED}", redacted)
    redacted = EMAIL_PATTERN.sub(REDACTED, redacted)
    return PHONE_PATTERN.sub(REDACTED, redacted)


def redact_value(value: object) -> object:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in cast("dict[object, object]", value).items()}
    if isinstance(value, list):
        return [redact_value(item) for item in cast("list[object]", value)]
    return value


def trace_text(text: str, limit: int = TRACE_TEXT_LIMIT) -> str:
    return redact(text)[:limit]
