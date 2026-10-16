from ipaddress import IPv4Address, IPv6Address, ip_address
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.errors import request_id_of
from motionile.core.logging import redact
from motionile.modules.audit.models import AuditLogEntry
from motionile.modules.audit.repository import AuditRepository
from motionile.modules.audit.schemas import AuditContext, AuditEvent


def parse_ip(value: str | None) -> IPv4Address | IPv6Address | None:
    if value is None:
        return None
    try:
        return ip_address(value)
    except ValueError:
        return None


def context_from_request(request: Request) -> AuditContext:
    client = request.client
    return AuditContext(
        ip=parse_ip(client.host if client is not None else None),
        user_agent=request.headers.get("user-agent"),
        request_id=request_id_of(request),
    )


async def record(session: AsyncSession, event: AuditEvent, context: AuditContext | None = None) -> UUID:
    sanitized = event.model_copy(update={"metadata": redact(event.metadata)})
    entry = await AuditRepository(session).insert(sanitized, context or AuditContext())
    return entry.id


async def recent_for_user(session: AsyncSession, user_id: UUID, limit: int = 20) -> list[AuditLogEntry]:
    return await AuditRepository(session).recent_for_user(user_id, limit)
