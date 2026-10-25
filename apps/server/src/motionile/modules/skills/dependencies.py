from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from motionile.core.dependencies import ResourcesDep
from motionile.core.errors import UnauthorizedError
from motionile.modules.access import SkillsManageDep
from motionile.modules.audit import AuditContext, context_from_request
from motionile.modules.skills.factory import build_skills_service
from motionile.modules.skills.service import SkillsService


@dataclass(frozen=True, slots=True)
class SkillsAdmin:
    user_id: UUID
    context: AuditContext


def get_skills_service(resources: ResourcesDep) -> SkillsService:
    return build_skills_service(resources)


def skills_admin(request: Request, principal: SkillsManageDep) -> SkillsAdmin:
    if principal.user_id is None:
        raise UnauthorizedError(code="unauthenticated")
    return SkillsAdmin(principal.user_id, context_from_request(request))


SkillsServiceDep = Annotated[SkillsService, Depends(get_skills_service)]
SkillsAdminDep = Annotated[SkillsAdmin, Depends(skills_admin)]
