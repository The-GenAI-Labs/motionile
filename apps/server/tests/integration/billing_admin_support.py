from dataclasses import dataclass
from typing import Any

from httpx import Response
from sqlalchemy import text
from tests.integration.billing_support import BillingApi

from motionile.core.ids import new_id
from motionile.modules.access import invalidate_user_access

ADMIN_BASE = "/v1/admin/billing"
ROLE_PREFIX = "itest_"
UNKNOWN_ID = "00000000-0000-7000-8000-00000000dead"


@dataclass(frozen=True)
class CallOptions:
    body: dict[str, Any] | None = None
    params: dict[str, Any] | None = None
    key: str | None = None
    as_user: bool = False


async def become(api: BillingApi, *roles: str) -> None:
    async with api.database.transaction() as session:
        await session.execute(
            text(
                "DELETE FROM user_roles WHERE user_id = :user_id AND role_id IN "
                "(SELECT id FROM roles WHERE key IN ('admin', 'super_admin') OR key LIKE 'itest\\_%')"
            ),
            {"user_id": api.other_id},
        )
    for role in roles:
        await api.grant_role(api.other_id, role)
    await invalidate_user_access(api.resources.redis_store, api.other_id)


async def create_role(api: BillingApi, suffix: str, *permissions: str) -> str:
    key = f"{ROLE_PREFIX}{suffix}"
    async with api.database.transaction() as session:
        role_id = new_id()
        await session.execute(
            text("INSERT INTO roles (id, key, name, is_system) VALUES (:id, :key, :name, false)"),
            {"id": role_id, "key": key, "name": f"Integration {suffix}"},
        )
        await session.execute(
            text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT :role_id, id FROM permissions WHERE key = ANY(:keys)"
            ),
            {"role_id": role_id, "keys": list(permissions)},
        )
    return key


async def drop_custom_roles(api: BillingApi) -> None:
    async with api.database.transaction() as session:
        await session.execute(
            text("DELETE FROM user_roles WHERE role_id IN (SELECT id FROM roles WHERE key LIKE 'itest\\_%')")
        )
        await session.execute(text("DELETE FROM roles WHERE key LIKE 'itest\\_%'"))
    await invalidate_user_access(api.resources.redis_store, api.other_id)


async def call(api: BillingApi, method: str, path: str, options: CallOptions | None = None) -> Response:
    chosen = options or CallOptions()
    client = api.primary if chosen.as_user else api.other
    return await client.request(
        method,
        f"{ADMIN_BASE}{path}",
        json=chosen.body,
        params=chosen.params,
        headers=api.headers(client, chosen.key),
    )


async def get(api: BillingApi, path: str, **params: Any) -> Response:
    return await call(api, "GET", path, CallOptions(params=params or None))


async def post(api: BillingApi, path: str, body: dict[str, Any] | None = None, *, key: str | None = None) -> Response:
    return await call(api, "POST", path, CallOptions(body=body if body is not None else {}, key=key))


async def patch(api: BillingApi, path: str, body: dict[str, Any]) -> Response:
    return await call(api, "PATCH", path, CallOptions(body=body))


def pack_body(code: str, **overrides: Any) -> dict[str, Any]:
    return {
        "code": code,
        "kind": "credit_pack",
        "name": "Admin pack",
        "description": "Created by an administrator",
        "pricePaise": 29_900,
        "creditsGranted": 150,
        "features": ["150 credits"],
        "sortOrder": 5,
        "isActive": True,
        **overrides,
    }


def plan_body(code: str, plan_key: str = "growth", interval: str = "month", **overrides: Any) -> dict[str, Any]:
    return {
        "code": code,
        "kind": "subscription",
        "name": f"Growth {interval}",
        "pricePaise": 59_900,
        "creditsGranted": 400,
        "planKey": plan_key,
        "interval": interval,
        "isActive": True,
        **overrides,
    }


async def created_product(api: BillingApi, body: dict[str, Any]) -> dict[str, Any]:
    response = await post(api, "/products", body)
    assert response.status_code == 201, response.text
    payload: dict[str, Any] = response.json()
    return payload


async def listed(api: BillingApi, path: str, **params: Any) -> list[dict[str, Any]]:
    response = await get(api, path, **params)
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items
