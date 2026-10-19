from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
from tests.integration.billing_admin_support import (
    UNKNOWN_ID,
    CallOptions,
    become,
    call,
    create_role,
    drop_custom_roles,
)
from tests.integration.billing_support import BillingApi

from motionile.core.errors import PROBLEM_MEDIA_TYPE

READ = "billing.read"
PRODUCTS = "billing.products.manage"
REFUNDS = "billing.refunds.create"
CREDITS = "billing.credits.adjust"
WEBHOOKS = "billing.webhooks.manage"
ALL_PERMISSIONS = (READ, PRODUCTS, REFUNDS, CREDITS, WEBHOOKS)
SUPER_ADMIN_ONLY = {REFUNDS, CREDITS}
ROLE_SUFFIX = {READ: "read", PRODUCTS: "products", REFUNDS: "refunds", CREDITS: "credits", WEBHOOKS: "webhooks"}


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    permission: str


ENDPOINTS = (
    Endpoint("GET", "/products", READ),
    Endpoint("GET", f"/products/{UNKNOWN_ID}", READ),
    Endpoint("GET", "/payments", READ),
    Endpoint("GET", f"/payments/{UNKNOWN_ID}", READ),
    Endpoint("GET", "/orders", READ),
    Endpoint("GET", f"/orders/{UNKNOWN_ID}", READ),
    Endpoint("GET", "/refunds", READ),
    Endpoint("GET", f"/refunds/{UNKNOWN_ID}", READ),
    Endpoint("GET", "/subscriptions", READ),
    Endpoint("GET", f"/subscriptions/{UNKNOWN_ID}", READ),
    Endpoint("GET", f"/users/{UNKNOWN_ID}/credits", READ),
    Endpoint("GET", f"/users/{UNKNOWN_ID}/credits/ledger", READ),
    Endpoint("GET", "/reconciliation/runs", READ),
    Endpoint("GET", f"/reconciliation/runs/{UNKNOWN_ID}", READ),
    Endpoint("GET", f"/reconciliation/runs/{UNKNOWN_ID}/report", READ),
    Endpoint("GET", "/analytics/revenue", READ),
    Endpoint("GET", "/analytics/subscriptions", READ),
    Endpoint("GET", "/analytics/credits", READ),
    Endpoint("POST", "/products", PRODUCTS),
    Endpoint("PATCH", f"/products/{UNKNOWN_ID}", PRODUCTS),
    Endpoint("POST", f"/products/{UNKNOWN_ID}/duplicate", PRODUCTS),
    Endpoint("POST", f"/products/{UNKNOWN_ID}/activate", PRODUCTS),
    Endpoint("POST", f"/products/{UNKNOWN_ID}/deactivate", PRODUCTS),
    Endpoint("POST", f"/products/{UNKNOWN_ID}/sync-plan", PRODUCTS),
    Endpoint("POST", f"/payments/{UNKNOWN_ID}/refunds", REFUNDS),
    Endpoint("POST", f"/subscriptions/{UNKNOWN_ID}/cancel", REFUNDS),
    Endpoint("POST", f"/users/{UNKNOWN_ID}/credits/adjust", CREDITS),
    Endpoint("GET", "/webhooks", WEBHOOKS),
    Endpoint("GET", f"/webhooks/{UNKNOWN_ID}", WEBHOOKS),
    Endpoint("POST", f"/webhooks/{UNKNOWN_ID}/reprocess", WEBHOOKS),
)
REACHED = {200, 202, 404, 422}


@pytest.fixture
async def roles(billing_api: BillingApi) -> AsyncIterator[BillingApi]:
    yield billing_api
    await drop_custom_roles(billing_api)


async def probe(api: BillingApi, endpoint: Endpoint, *, as_user: bool = False) -> int:
    body: dict[str, Any] | None = {} if endpoint.method in {"POST", "PATCH"} else None
    response = await call(api, endpoint.method, endpoint.path, CallOptions(body=body, as_user=as_user))
    if response.status_code == 403:
        assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
        assert response.json()["code"] == "permission_denied"
    return response.status_code


def test_the_catalogue_lists_every_billing_admin_permission() -> None:
    assert {endpoint.permission for endpoint in ENDPOINTS} == set(ALL_PERMISSIONS)
    assert len(ENDPOINTS) == len({(endpoint.method, endpoint.path) for endpoint in ENDPOINTS})


async def test_the_catalogue_covers_every_registered_billing_admin_route(billing_api: BillingApi) -> None:
    paths: dict[str, dict[str, object]] = billing_api.app.openapi()["paths"]
    registered = {
        (method, path)
        for path, operations in paths.items()
        if path.startswith("/v1/admin/billing")
        for method in operations
    }

    assert len(registered) == len(ENDPOINTS)


async def test_anonymous_callers_are_turned_away(roles: BillingApi) -> None:
    for endpoint in ENDPOINTS:
        body: dict[str, Any] | None = {} if endpoint.method in {"POST", "PATCH"} else None
        response = await roles.anonymous.request(
            endpoint.method,
            f"/v1/admin/billing{endpoint.path}",
            json=body,
            headers={"Idempotency-Key": roles.keys()},
        )
        assert response.status_code in {401, 403}, endpoint


async def test_a_user_without_a_role_is_forbidden_everywhere(roles: BillingApi) -> None:
    for endpoint in ENDPOINTS:
        assert await probe(roles, endpoint, as_user=True) == 403, endpoint


async def test_an_admin_holds_everything_except_refunds_and_credit_adjustments(roles: BillingApi) -> None:
    await become(roles, "admin")

    for endpoint in ENDPOINTS:
        status = await probe(roles, endpoint)
        if endpoint.permission in SUPER_ADMIN_ONLY:
            assert status == 403, endpoint
        else:
            assert status in REACHED, (endpoint, status)


async def test_a_super_admin_reaches_every_endpoint(roles: BillingApi) -> None:
    await become(roles, "super_admin")

    for endpoint in ENDPOINTS:
        assert await probe(roles, endpoint) in REACHED, endpoint


@pytest.mark.parametrize("permission", ALL_PERMISSIONS)
async def test_a_role_holding_one_permission_reaches_only_its_endpoints(roles: BillingApi, permission: str) -> None:
    role = await create_role(roles, ROLE_SUFFIX[permission], permission)
    await become(roles, role)

    for endpoint in ENDPOINTS:
        status = await probe(roles, endpoint)
        if endpoint.permission == permission:
            assert status in REACHED, (endpoint, status)
        else:
            assert status == 403, (endpoint, status)


async def test_removing_the_role_removes_the_access_at_once(roles: BillingApi) -> None:
    await become(roles, "admin")
    assert await probe(roles, ENDPOINTS[0]) == 200

    await become(roles)

    assert await probe(roles, ENDPOINTS[0]) == 403
