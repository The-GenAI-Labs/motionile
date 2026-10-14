import logging
import sys
from collections.abc import Mapping, Sequence
from typing import cast

import orjson
import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from motionile.core.config import Settings

REDACTED = "[REDACTED]"
SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "proxy_authorization",
        "cookie",
        "cookies",
        "set_cookie",
        "password",
        "token",
        "secret",
        "api_key",
        "otp",
        "otp_code",
        "verification_code",
        "x_csrf_token",
        "x_turnstile_token",
        "idempotency_key",
        "signature",
        "x_razorpay_signature",
    }
)
SENSITIVE_SUFFIXES = ("_token", "_secret", "_password", "_key_id", "_api_key", "_signature")


def normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def is_sensitive_key(key: str) -> bool:
    normalized = normalize_key(key)
    return normalized in SENSITIVE_KEYS or normalized.endswith(SENSITIVE_SUFFIXES) or "password" in normalized


def redact(value: object) -> object:
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        return {str(key): REDACTED if is_sensitive_key(str(key)) else redact(item) for key, item in mapping.items()}
    if isinstance(value, list | tuple):
        items = cast("Sequence[object]", value)
        return [redact(item) for item in items]
    return value


def redact_sensitive_fields(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    return {key: REDACTED if is_sensitive_key(key) else redact(value) for key, value in event_dict.items()}


def _shared_processors() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        redact_sensitive_fields,
    ]


def _json_dumps(event: object, **_: object) -> bytes:
    return orjson.dumps(event, default=str)


def configure_logging(settings: Settings) -> None:
    level = logging.getLevelNamesMapping()[settings.logging.level.value]
    logging.basicConfig(level=level, stream=sys.stdout, format="%(message)s", force=True)
    if settings.is_local:
        structlog.configure(
            processors=[*_shared_processors(), structlog.dev.ConsoleRenderer()],
            wrapper_class=structlog.make_filtering_bound_logger(level),
            logger_factory=structlog.PrintLoggerFactory(sys.stdout),
            cache_logger_on_first_use=False,
        )
        return
    structlog.configure(
        processors=[
            *_shared_processors(),
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(serializer=_json_dumps),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.BytesLoggerFactory(sys.stdout.buffer),
        cache_logger_on_first_use=False,
    )


def bind_request_context(**values: str) -> None:
    structlog.contextvars.bind_contextvars(**values)


def clear_request_context() -> None:
    structlog.contextvars.clear_contextvars()
