from typing import Any, ClassVar

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.db import run_after_commit
from motionile.core.events import DomainEvent, EventBus, UnknownSubscriptionError


class VideoRendered(DomainEvent):
    name: ClassVar[str] = "video.rendered"

    video_id: str


class UserDeleted(DomainEvent):
    name: ClassVar[str] = "user.deleted"

    user_id: str


class RecordingDeferrer:
    def __init__(self) -> None:
        self.deferred: list[tuple[str, DomainEvent]] = []

    async def defer(self, subscription_name: str, event: DomainEvent) -> None:
        self.deferred.append((subscription_name, event))


async def test_publish_calls_matching_handlers_only() -> None:
    bus = EventBus()
    received: list[DomainEvent] = []

    async def on_rendered(event: VideoRendered) -> None:
        received.append(event)

    bus.subscribe(VideoRendered, on_rendered, name="notifications.on_rendered")

    await bus.publish(VideoRendered(video_id="v1"))
    await bus.publish(UserDeleted(user_id="u1"))

    assert received == [VideoRendered(video_id="v1")]


async def test_handler_failure_does_not_stop_other_handlers() -> None:
    bus = EventBus()
    received: list[str] = []

    async def broken(_: VideoRendered) -> None:
        message = "boom"
        raise RuntimeError(message)

    async def working(event: VideoRendered) -> None:
        received.append(event.video_id)

    bus.subscribe(VideoRendered, broken, name="a.broken")
    bus.subscribe(VideoRendered, working, name="b.working")

    await bus.publish(VideoRendered(video_id="v2"))

    assert received == ["v2"]


def test_subscription_names_are_unique() -> None:
    bus = EventBus()

    async def handler(_: VideoRendered) -> None:
        return None

    bus.subscribe(VideoRendered, handler, name="same")

    with pytest.raises(ValueError, match="already registered"):
        bus.subscribe(VideoRendered, handler, name="same")


async def test_task_subscriptions_are_deferred_not_called() -> None:
    deferrer = RecordingDeferrer()
    bus = EventBus(deferrer)
    called: list[VideoRendered] = []

    async def handler(event: VideoRendered) -> None:
        called.append(event)

    bus.subscribe(VideoRendered, handler, name="publishing.on_rendered", run_as_task=True)
    event = VideoRendered(video_id="v3")

    await bus.publish(event)

    assert called == []
    assert deferrer.deferred == [("publishing.on_rendered", event)]


async def test_dispatch_validates_payload_and_runs_handler() -> None:
    bus = EventBus()
    called: list[VideoRendered] = []

    async def handler(event: VideoRendered) -> None:
        called.append(event)

    bus.subscribe(VideoRendered, handler, name="publishing.on_rendered", run_as_task=True)
    payload: dict[str, Any] = {"video_id": "v4"}

    await bus.dispatch("publishing.on_rendered", payload)

    assert called == [VideoRendered(video_id="v4")]
    with pytest.raises(UnknownSubscriptionError):
        await bus.dispatch("missing", payload)


async def test_publish_after_commit_waits_for_commit() -> None:
    bus = EventBus()
    called: list[VideoRendered] = []

    async def handler(event: VideoRendered) -> None:
        called.append(event)

    bus.subscribe(VideoRendered, handler, name="x.handler")
    session = AsyncSession()

    bus.publish_after_commit(session, VideoRendered(video_id="v5"))
    assert called == []

    await run_after_commit(session)
    assert called == [VideoRendered(video_id="v5")]
    await session.close()
