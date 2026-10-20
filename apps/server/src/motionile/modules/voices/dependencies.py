from typing import Annotated
from uuid import UUID

from fastapi import Depends

from motionile.core.dependencies import ResourcesDep
from motionile.core.errors import UnauthorizedError
from motionile.modules.auth import CurrentPrincipalDep
from motionile.modules.voices.clone_service import CloneService
from motionile.modules.voices.factory import build_clone_service, build_voices_service
from motionile.modules.voices.service import VoicesService
from motionile.modules.voices.tasks import defer_clone


def get_voices_service(resources: ResourcesDep) -> VoicesService:
    return build_voices_service(resources)


def get_clone_service(resources: ResourcesDep) -> CloneService:
    return build_clone_service(resources, defer_clone)


def get_current_user_id(principal: CurrentPrincipalDep) -> UUID:
    if principal.user_id is None:
        raise UnauthorizedError(code="unauthenticated")
    return principal.user_id


VoicesServiceDep = Annotated[VoicesService, Depends(get_voices_service)]
CloneServiceDep = Annotated[CloneService, Depends(get_clone_service)]
CurrentUserIdDep = Annotated[UUID, Depends(get_current_user_id)]
