from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

import structlog
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.db import after_commit
from motionile.core.tasks.registry import Queue, task

logger = structlog.get_logger(__name__)


class DomainEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: ClassVar[str]


type EventHandler[EventT: DomainEvent] = Callable[[EventT], Awaitable[None]]


@dataclass(frozen=True)
class Subscription:
    name: str
    event_type: type[DomainEvent]
    handler: Callable[[Any], Awaitable[None]]
    run_as_task: bool


class EventTaskDeferrer(Protocol):
    async def defer(self, subscription_name: str, event: DomainEvent) -> None: ...


class UnknownSubscriptionError(LookupError):
    def __init__(self, name: str) -> None:
        super().__init__(f"no event subscription named {name!r}")


class EventBus:
    def __init__(self, deferrer: EventTaskDeferrer | None = None) -> None:
        self.deferrer = deferrer
        self._by_type: defaultdict[type[DomainEvent], list[Subscription]] = defaultdict(list)
        self._by_name: dict[str, Subscription] = {}

    def subscribe[EventT: DomainEvent](
        self,
        event_type: type[EventT],
        handler: EventHandler[EventT],
        *,
        name: str,
        run_as_task: bool = False,
    ) -> None:
        if name in self._by_name:
            message = f"event subscription {name!r} is already registered"
            raise ValueError(message)
        subscription = Subscription(name=name, event_type=event_type, handler=handler, run_as_task=run_as_task)
        self._by_type[event_type].append(subscription)
        self._by_name[name] = subscription

    def subscriptions_for(self, event_type: type[DomainEvent]) -> list[Subscription]:
        return list(self._by_type.get(event_type, []))

    async def publish(self, event: DomainEvent) -> None:
        for subscription in self.subscriptions_for(type(event)):
            try:
                if subscription.run_as_task:
                    if self.deferrer is None:
                        message = "this event bus cannot run handlers as tasks"
                        raise RuntimeError(message)
                    await self.deferrer.defer(subscription.name, event)
                else:
                    await subscription.handler(event)
            except Exception:
                logger.exception("events.handler_failed", event_name=event.name, subscription=subscription.name)

    def publish_after_commit(self, session: AsyncSession, event: DomainEvent) -> None:
        async def publish_committed() -> None:
            await self.publish(event)

        after_commit(session, publish_committed)

    async def dispatch(self, subscription_name: str, payload: dict[str, Any]) -> None:
        subscription = self._by_name.get(subscription_name)
        if subscription is None:
            raise UnknownSubscriptionError(subscription_name)
        await subscription.handler(subscription.event_type.model_validate(payload))


event_bus = EventBus()


@task(name="events.dispatch", queue=Queue.DEFAULT)
async def dispatch_event(subscription: str, payload: dict[str, Any]) -> None:
    await event_bus.dispatch(subscription, payload)


class ProcrastinateEventDeferrer:
    async def defer(self, subscription_name: str, event: DomainEvent) -> None:
        await dispatch_event.defer_async(subscription=subscription_name, payload=event.model_dump(mode="json"))


event_bus.deferrer = ProcrastinateEventDeferrer()
