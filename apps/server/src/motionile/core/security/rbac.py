from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from starlette.requests import Request

from motionile.core.errors import ForbiddenError, UnauthorizedError

SUPER_ADMIN_ROLE = "super_admin"


class PrincipalKind(StrEnum):
    USER = "user"
    API_KEY = "api_key"
    SYSTEM = "system"


@dataclass(frozen=True)
class Principal:
    kind: PrincipalKind
    user_id: UUID | None = None
    roles: frozenset[str] = field(default_factory=frozenset[str])
    permissions: frozenset[str] = field(default_factory=frozenset[str])
    session_id: UUID | None = None
    api_key_id: UUID | None = None

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def has_permission(self, permission: str) -> bool:
        return self.kind is PrincipalKind.SYSTEM or SUPER_ADMIN_ROLE in self.roles or permission in self.permissions


class PermissionDeniedError(ForbiddenError):
    default_code = "permission_denied"
    title = "Permission denied"


def require_permission(principal: Principal | None, permission: str) -> Principal:
    if principal is None:
        raise UnauthorizedError
    if not principal.has_permission(permission):
        raise PermissionDeniedError(f"Missing permission {permission}.")
    return principal


def principal_of(request: Request) -> Principal | None:
    value: object = getattr(request.state, "principal", None)
    return value if isinstance(value, Principal) else None
