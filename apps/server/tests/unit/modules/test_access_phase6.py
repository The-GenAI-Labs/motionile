from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.errors import ConflictError, ForbiddenError, ValidationAppError
from motionile.core.redis import RedisStore
from motionile.core.security.rbac import Principal, PrincipalKind
from motionile.modules.access.repository import AccessRepository
from motionile.modules.access.service import AccessService, EffectiveAccess


def principal(user_id: UUID) -> Principal:
    return Principal(kind=PrincipalKind.USER, user_id=user_id)


def service() -> AccessService:
    return AccessService(cast("AsyncSession", SimpleNamespace()), cast("RedisStore", SimpleNamespace()))


def test_permission_keys_reject_unknown_and_duplicate_values() -> None:
    access = service()
    with pytest.raises(ValidationAppError) as unknown:
        access.validated_permissions(["unknown.manage"])
    with pytest.raises(ValidationAppError) as duplicate:
        access.validated_permissions(["users.read", "users.read"])
    assert unknown.value.code == "invalid_permissions"
    assert duplicate.value.code == "invalid_permissions"


@pytest.mark.asyncio
async def test_admin_cannot_grant_permissions_they_do_not_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    access = service()
    actor = principal(UUID("0199eb00-0000-7000-8000-000000000001"))
    monkeypatch.setattr(
        access,
        "effective",
        AsyncMock(return_value=EffectiveAccess(frozenset({"admin"}), frozenset({"users.read"}))),
    )
    with pytest.raises(ForbiddenError) as error:
        await access.ensure_actor_can_grant(actor, {"roles.manage"})
    assert error.value.code == "permission_escalation"


@pytest.mark.asyncio
async def test_super_admin_cannot_remove_their_own_role() -> None:
    access = service()
    actor_id = UUID("0199eb00-0000-7000-8000-000000000001")
    role_id = UUID("0199eb00-0000-7000-8000-000000000002")
    access.repository = cast(
        "AccessRepository", SimpleNamespace(role=AsyncMock(return_value=SimpleNamespace(key="super_admin")))
    )
    with pytest.raises(ConflictError) as error:
        await access.remove(principal(actor_id), actor_id, role_id)
    assert error.value.code == "self_super_admin_removal"


@pytest.mark.asyncio
async def test_last_super_admin_cannot_be_removed() -> None:
    access = service()
    actor_id = UUID("0199eb00-0000-7000-8000-000000000001")
    target_id = UUID("0199eb00-0000-7000-8000-000000000002")
    role_id = UUID("0199eb00-0000-7000-8000-000000000003")
    access.repository = cast(
        "AccessRepository",
        SimpleNamespace(
            role=AsyncMock(return_value=SimpleNamespace(key="super_admin")),
            count_role_key=AsyncMock(return_value=1),
        ),
    )
    with pytest.raises(ConflictError) as error:
        await access.remove(principal(actor_id), target_id, role_id)
    assert error.value.code == "last_super_admin"
