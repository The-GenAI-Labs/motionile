from collections.abc import AsyncIterator
from ipaddress import ip_address
from uuid import UUID

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.auth import AuthDatabase, AuthState, FakeAuthRepository, FakeUsersService, state_of
from tests.fakes.resources import FIXED_NOW, make_resources
from tests.fakes.settings import make_settings

from motionile.core.clock import FrozenClock
from motionile.core.events import EventBus
from motionile.core.redis import RedisStore
from motionile.core.resources import Resources
from motionile.modules.audit import AuditContext, AuditEvent
from motionile.modules.auth import service as service_module
from motionile.modules.auth.oauth import service as oauth_service_module
from motionile.modules.auth.runtime import AuthRuntime
from motionile.modules.auth.service import AuthService
from motionile.modules.notifications import Notification


async def fake_assign(session: AsyncSession, user_id: UUID) -> None:
    state_of(session).roles[user_id] = ["user"]


async def fake_roles(session: AsyncSession, user_id: UUID) -> list[str]:
    return state_of(session).roles.get(user_id, [])


async def fake_audit(session: AsyncSession, event: AuditEvent, context: AuditContext | None = None) -> UUID:
    del context
    state_of(session).audit.append(event)
    return UUID(int=1)


def fake_enqueue(resources: Resources, session: AsyncSession, message: Notification) -> None:
    del resources
    state_of(session).notifications.append(message)


@pytest.fixture
async def auth_service(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AuthService]:
    state = AuthState()
    resources = make_resources(make_settings(), clock=FrozenClock(FIXED_NOW))
    await resources.redis.aclose()
    redis = FakeRedis()
    resources.redis = redis
    resources.redis_store = RedisStore(redis, resources.redis_store.keys)
    original_database = resources.database
    resources.database = AuthDatabase(state)
    resources.events = EventBus()
    for module in (service_module, oauth_service_module):
        monkeypatch.setattr(module, "AuthRepository", FakeAuthRepository)
        monkeypatch.setattr(module, "UsersService", FakeUsersService)
        monkeypatch.setattr(module, "assign_default_role", fake_assign)
    monkeypatch.setattr(service_module, "roles_for_user", fake_roles)
    monkeypatch.setattr(service_module, "record", fake_audit)
    monkeypatch.setattr(service_module, "enqueue_notification", fake_enqueue)
    service = AuthService(
        AuthRuntime(resources), AuditContext(ip=ip_address("203.0.113.1"), user_agent="Firefox/143 Windows")
    )
    yield service
    resources.database = original_database
    await resources.aclose()


@pytest.fixture
def auth_state(auth_service: AuthService) -> AuthState:
    database = auth_service.resources.database
    assert isinstance(database, AuthDatabase)
    return database.state


@pytest.fixture
def auth_clock(auth_service: AuthService) -> FrozenClock:
    clock = auth_service.resources.clock
    assert isinstance(clock, FrozenClock)
    return clock
