from datetime import datetime
from uuid import UUID

from pydantic import Field

from motionile.core.schemas import ResponseModel, StrictModel


class RoleResponse(ResponseModel):
    id: UUID
    key: str
    name: str
    description: str | None
    is_system: bool
    permissions: list[str]
    user_count: int = 0
    created_at: datetime
    updated_at: datetime


class PermissionResponse(ResponseModel):
    key: str
    description: str | None


class AccessCatalogResponse(ResponseModel):
    roles: list[RoleResponse]
    permissions: list[PermissionResponse]


class RoleCreateRequest(StrictModel):
    key: str = Field(min_length=2, max_length=40, pattern=r"^[a-z][a-z_]{1,39}$")
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] = Field(default_factory=list[str], max_length=100)


class RoleUpdateRequest(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] | None = Field(default=None, max_length=100)


class UserRoleRequest(StrictModel):
    role_id: UUID
