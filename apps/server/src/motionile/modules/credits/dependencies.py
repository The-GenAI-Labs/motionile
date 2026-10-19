from typing import Annotated
from uuid import UUID

from fastapi import Depends

from motionile.core.dependencies import ClockDep, SettingsDep
from motionile.core.errors import UnauthorizedError
from motionile.modules.auth import CurrentPrincipalDep
from motionile.modules.credits.service import CreditsService


def get_credits_service(clock: ClockDep, settings: SettingsDep) -> CreditsService:
    return CreditsService(clock, settings.billing)


def get_current_user_id(principal: CurrentPrincipalDep) -> UUID:
    if principal.user_id is None:
        raise UnauthorizedError(code="unauthenticated")
    return principal.user_id


CreditsServiceDep = Annotated[CreditsService, Depends(get_credits_service)]
CurrentUserIdDep = Annotated[UUID, Depends(get_current_user_id)]
