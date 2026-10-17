from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.modules.billing.records import WebhookEventRecord

UNHANDLED_EVENT = "unhandled_event"
UNKNOWN_ENTITY = "unknown_entity"
STALE_EVENT = "stale"


@dataclass(frozen=True)
class Outcome:
    ignored_reason: str | None = None

    @property
    def ignored(self) -> bool:
        return self.ignored_reason is not None


PROCESSED = Outcome()


def ignored(reason: str) -> Outcome:
    return Outcome(reason)


type EventHandler = Callable[[AsyncSession, WebhookEventRecord], Awaitable[Outcome]]


class DuplicateHandlerError(ValueError):
    def __init__(self, event_type: str) -> None:
        super().__init__(f"a handler is already registered for {event_type}")


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, EventHandler] = {}

    def register_handler(self, event_type: str, handler: EventHandler) -> None:
        if event_type in self._handlers:
            raise DuplicateHandlerError(event_type)
        self._handlers[event_type] = handler

    def handler_for(self, event_type: str) -> EventHandler | None:
        return self._handlers.get(event_type)

    def event_types(self) -> frozenset[str]:
        return frozenset(self._handlers)
