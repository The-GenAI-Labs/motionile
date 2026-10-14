from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.ids import new_id
from motionile.modules.audit.models import AuditLogEntry
from motionile.modules.audit.schemas import AuditContext, AuditEvent


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def insert(self, event: AuditEvent, context: AuditContext) -> AuditLogEntry:
        entry = AuditLogEntry(
            id=new_id(),
            actor_user_id=event.actor_user_id,
            actor_type=event.actor_type.value,
            action=event.action,
            target_type=event.target_type,
            target_id=event.target_id,
            ip=str(context.ip) if context.ip is not None else None,
            user_agent=context.user_agent,
            request_id=context.request_id,
            metadata_=event.metadata,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry
