from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.modules.audit import ActorType, AuditEvent
from motionile.modules.audit import record as record_audit
from motionile.modules.prompts.domain import Actor, PromptAction, Subject


async def audit(
    session: AsyncSession, actor: Actor | None, action: PromptAction, subject: Subject, metadata: dict[str, Any]
) -> None:
    event = AuditEvent(
        action=action.value,
        actor_type=ActorType.ADMIN if actor is not None else ActorType.SYSTEM,
        actor_user_id=actor.user_id if actor is not None else None,
        target_type=subject.type,
        target_id=str(subject.id),
        metadata=metadata,
    )
    await record_audit(session, event, actor.context if actor is not None else None)
