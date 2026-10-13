from datetime import UTC, datetime

from tests.fakes.storage import InMemoryStorage

from motionile.core.clock import Clock, FrozenClock
from motionile.core.config import Settings
from motionile.core.resources import Resources, build_resources

FAKE_APPLICATION_NAME = "motionile-tests"
FIXED_NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def make_resources(settings: Settings, *, clock: Clock | None = None) -> Resources:
    resources = build_resources(settings, application_name=FAKE_APPLICATION_NAME, clock=clock or FrozenClock(FIXED_NOW))
    resources.storage = InMemoryStorage()
    return resources
