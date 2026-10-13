import logging
import sys

import orjson
import structlog
from structlog.typing import Processor

from motionile.core.config import Settings


def _shared_processors() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]


def _json_dumps(event: object, **_: object) -> bytes:
    return orjson.dumps(event, default=str)


def configure_logging(settings: Settings) -> None:
    level = logging.getLevelNamesMapping()[settings.log_level.value]
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
