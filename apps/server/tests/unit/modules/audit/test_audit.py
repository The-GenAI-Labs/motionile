from ipaddress import ip_address
from typing import cast
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from motionile.modules.audit import ActorType, AuditContext, AuditEvent, AuditLogEntry, context_from_request, record
from motionile.modules.audit.service import parse_ip


class RecordingSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushed = False

    def add(self, entry: object) -> None:
        self.added.append(entry)

    async def flush(self) -> None:
        self.flushed = True


def make_request(headers: dict[str, str], client: tuple[str, int] | None) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/x",
        "headers": [(name.lower().encode(), value.encode()) for name, value in headers.items()],
        "client": client,
        "state": {"request_id": "req-123"},
    }
    return Request(scope)


@pytest.mark.parametrize("action", ["auth.login.succeeded", "billing.order.paid", "user.deleted"])
def test_accepts_dotted_snake_case_actions(action: str) -> None:
    assert AuditEvent(action=action, actor_type=ActorType.USER).action == action


@pytest.mark.parametrize("action", ["login", "Auth.Login", "auth..login", "auth.login.", "9auth.login", "auth-login.x"])
def test_rejects_malformed_actions(action: str) -> None:
    with pytest.raises(ValidationError):
        AuditEvent(action=action, actor_type=ActorType.SYSTEM)


def test_parse_ip_tolerates_garbage() -> None:
    assert parse_ip("203.0.113.5") == ip_address("203.0.113.5")
    assert parse_ip("not-an-ip") is None
    assert parse_ip(None) is None


def test_context_from_request_reads_ip_user_agent_and_request_id() -> None:
    request = make_request({"User-Agent": "x" * 600}, ("198.51.100.7", 4000))

    context = context_from_request(request)

    assert context.ip == ip_address("198.51.100.7")
    assert context.user_agent == "x" * 512
    assert context.request_id == "req-123"


def test_context_from_request_without_client() -> None:
    context = context_from_request(make_request({}, None))

    assert context.ip is None
    assert context.user_agent is None


async def test_record_redacts_metadata_and_flushes() -> None:
    session = RecordingSession()
    actor = UUID("01920000-0000-7000-8000-000000000009")
    event = AuditEvent(
        action="auth.password.changed",
        actor_type=ActorType.USER,
        actor_user_id=actor,
        target_type="user",
        target_id=str(actor),
        metadata={"password": "hunter2", "nested": {"api_key": "k", "reason": "reset"}},
    )

    entry_id = await record(
        cast("AsyncSession", session),
        event,
        AuditContext(ip=ip_address("203.0.113.1"), user_agent="ua", request_id="r1"),
    )

    entry = session.added[0]
    assert isinstance(entry, AuditLogEntry)
    assert session.flushed
    assert entry.id == entry_id
    assert entry.actor_type == "user"
    assert entry.ip == "203.0.113.1"
    assert entry.metadata_ == {"password": "[REDACTED]", "nested": {"api_key": "[REDACTED]", "reason": "reset"}}
