from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.db import after_commit
from motionile.modules.prompts.auditing import audit
from motionile.modules.prompts.domain import ACTIVATION_ACTIONS, AUDIT_TEMPLATE_TARGET, Activation, Subject
from motionile.modules.prompts.exceptions import ActivationConflictError
from motionile.modules.prompts.models import PromptTemplate, PromptVersion
from motionile.modules.prompts.repository import PromptRepository
from motionile.modules.prompts.store import invalidate_active_prompts_after_commit


async def switch_active(
    session: AsyncSession,
    repository: PromptRepository,
    template: PromptTemplate,
    target: PromptVersion,
    change: Activation,
) -> None:
    previous = template.active_version_id
    if not await repository.set_active(template.id, target.id, previous):
        raise ActivationConflictError
    await audit(
        session,
        change.actor,
        ACTIVATION_ACTIONS[change.kind],
        Subject(AUDIT_TEMPLATE_TARGET, template.id),
        {
            "key": template.key,
            "version": target.version,
            "version_id": str(target.id),
            "from_version_id": str(previous) if previous is not None else None,
            **(change.extra or {}),
        },
    )
    after_commit(session, invalidate_active_prompts_after_commit)
