from typing import Annotated

from fastapi import Depends

from motionile.core.dependencies import DatabaseDep, PrincipalDep, RedisStoreDep
from motionile.core.errors import UnauthorizedError
from motionile.core.security.rbac import PermissionDeniedError, Principal
from motionile.modules.access.service import resolve_access


class RequirePermission:
    def __init__(self, permission: str) -> None:
        self.permission = permission

    async def __call__(self, principal: PrincipalDep, database: DatabaseDep, redis: RedisStoreDep) -> Principal:
        if principal is None or principal.user_id is None:
            raise UnauthorizedError(code="unauthenticated")
        async with database.transaction() as session:
            access = await resolve_access(session, redis, principal.user_id)
        if "super_admin" not in access.roles and self.permission not in access.permissions:
            raise PermissionDeniedError(f"Missing permission {self.permission}.")
        return Principal(
            kind=principal.kind,
            user_id=principal.user_id,
            roles=access.roles,
            permissions=access.permissions,
            session_id=principal.session_id,
            api_key_id=principal.api_key_id,
        )


UsersReadDep = Annotated[Principal, Depends(RequirePermission("users.read"))]
UsersManageDep = Annotated[Principal, Depends(RequirePermission("users.manage"))]
UsersRolesAssignDep = Annotated[Principal, Depends(RequirePermission("users.roles.assign"))]
RolesReadDep = Annotated[Principal, Depends(RequirePermission("roles.read"))]
RolesManageDep = Annotated[Principal, Depends(RequirePermission("roles.manage"))]
AuditReadDep = Annotated[Principal, Depends(RequirePermission("audit.read"))]
AnalyticsReadDep = Annotated[Principal, Depends(RequirePermission("analytics.read"))]
SettingsReadDep = Annotated[Principal, Depends(RequirePermission("settings.read"))]
SettingsManageDep = Annotated[Principal, Depends(RequirePermission("settings.manage"))]
FlagsManageDep = Annotated[Principal, Depends(RequirePermission("flags.manage"))]
CatalogManageDep = Annotated[Principal, Depends(RequirePermission("catalog.manage"))]
BillingReadDep = Annotated[Principal, Depends(RequirePermission("billing.read"))]
BillingProductsManageDep = Annotated[Principal, Depends(RequirePermission("billing.products.manage"))]
BillingRefundsCreateDep = Annotated[Principal, Depends(RequirePermission("billing.refunds.create"))]
BillingCreditsAdjustDep = Annotated[Principal, Depends(RequirePermission("billing.credits.adjust"))]
BillingWebhooksManageDep = Annotated[Principal, Depends(RequirePermission("billing.webhooks.manage"))]
RenderTestbedDep = Annotated[Principal, Depends(RequirePermission("render.testbed"))]
VoicesManageDep = Annotated[Principal, Depends(RequirePermission("voices.manage"))]
MusicManageDep = Annotated[Principal, Depends(RequirePermission("music.manage"))]
