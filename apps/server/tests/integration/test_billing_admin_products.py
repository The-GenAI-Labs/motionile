import asyncio
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.integration.billing_admin_support import (
    UNKNOWN_ID,
    become,
    created_product,
    get,
    listed,
    pack_body,
    patch,
    plan_body,
    post,
)
from tests.integration.billing_support import BillingApi

from motionile.core.ids import new_id
from motionile.modules.billing.admin_records import NewProduct
from motionile.modules.billing.admin_repository import SqlProductAdminRepository
from motionile.modules.billing.exceptions import ActivePlanConflictError, ProductCodeExistsError, ProductImmutableError


@pytest.fixture
async def admin(billing_api: BillingApi) -> BillingApi:
    await become(billing_api, "admin")
    return billing_api


async def plan_count(api: BillingApi) -> int:
    raw = await api.resources.redis_store.get(api.resources.redis_store.keys.key("fake_razorpay", "sequence", "plan"))
    return int(raw) if raw is not None else 0


async def public_codes(api: BillingApi) -> set[str]:
    listing = (await api.anonymous.get("/v1/billing/products")).json()
    return {item["code"] for group in listing.values() for item in group}


async def test_a_product_goes_through_its_whole_lifecycle(admin: BillingApi) -> None:
    pack = await created_product(admin, pack_body(f"adm_{new_id().hex[-8:]}"))
    assert (pack["version"], pack["isActive"], pack["isUsed"], pack["razorpayPlanId"]) == (1, True, False, None)

    code = f"gro_{new_id().hex[-8:]}"
    plan = await created_product(admin, plan_body(code, plan_key=f"grow_{new_id().hex[-6:]}"))
    assert (plan["isActive"], plan["razorpayPlanId"]) == (False, None)

    first = await post(admin, f"/products/{plan['id']}/sync-plan")
    second = await post(admin, f"/products/{plan['id']}/sync-plan")
    assert first.status_code == second.status_code == 200
    assert first.json()["razorpayPlanId"] == second.json()["razorpayPlanId"] is not None
    assert await plan_count(admin) == 1

    activated = await post(admin, f"/products/{plan['id']}/activate")
    assert activated.json()["isActive"] is True

    copy = await post(admin, f"/products/{plan['id']}/duplicate", {"pricePaise": 69_900, "name": "Growth v2"})
    assert copy.status_code == 201, copy.text
    duplicate = copy.json()
    assert (duplicate["code"], duplicate["version"], duplicate["isActive"], duplicate["isSample"]) == (
        f"{code}_v2",
        2,
        False,
        False,
    )
    assert (duplicate["pricePaise"], duplicate["name"], duplicate["planKey"], duplicate["interval"]) == (
        69_900,
        "Growth v2",
        plan["planKey"],
        "month",
    )
    assert duplicate["razorpayPlanId"] is None
    assert duplicate["supersedes"]["code"] == code

    await post(admin, f"/products/{duplicate['id']}/sync-plan")
    assert await plan_count(admin) == 2
    conflict = await post(admin, f"/products/{duplicate['id']}/activate")
    assert (conflict.status_code, conflict.json()["code"]) == (409, "active_plan_exists")
    assert code in conflict.json()["detail"]
    assert conflict.json()["activeProductCode"] == code

    assert (await post(admin, f"/products/{plan['id']}/deactivate")).json()["isActive"] is False
    assert (await post(admin, f"/products/{duplicate['id']}/activate")).json()["isActive"] is True

    original = (await get(admin, f"/products/{plan['id']}")).json()
    assert [link["code"] for link in original["supersededBy"]] == [f"{code}_v2"]
    assert original["supersedes"] is None
    actions = await admin.audit_actions()
    assert actions == [
        "billing.product.created",
        "billing.product.created",
        "billing.product.plan_synced",
        "billing.product.activated",
        "billing.product.duplicated",
        "billing.product.plan_synced",
        "billing.product.deactivated",
        "billing.product.activated",
    ]


async def test_activation_needs_a_synced_plan(admin: BillingApi) -> None:
    plan = await created_product(admin, plan_body(f"unsynced_{new_id().hex[-6:]}"))

    response = await post(admin, f"/products/{plan['id']}/activate")

    assert (response.status_code, response.json()["code"]) == (409, "plan_not_synced")


async def test_a_pack_has_no_plan_to_sync(admin: BillingApi) -> None:
    pack = await created_product(admin, pack_body(f"nop_{new_id().hex[-8:]}"))

    response = await post(admin, f"/products/{pack['id']}/sync-plan")

    assert (response.status_code, response.json()["code"]) == (422, "product_not_subscription")


async def test_a_plan_timeout_is_never_resent_and_a_retry_links_a_plan(admin: BillingApi) -> None:
    plan = await created_product(admin, plan_body(f"timeout_{new_id().hex[-6:]}"))
    await admin.arm_fault("create_plan", "timeout_after_create")

    failed = await post(admin, f"/products/{plan['id']}/sync-plan")

    assert (failed.status_code, failed.json()["code"]) == (503, "payment_provider_unavailable")
    assert "not linked to this product" in failed.json()["detail"]
    assert (await get(admin, f"/products/{plan['id']}")).json()["razorpayPlanId"] is None
    assert await plan_count(admin) == 1
    assert "billing.plan_sync_unconfirmed" in admin.recorded.alert_codes()

    retried = await post(admin, f"/products/{plan['id']}/sync-plan")

    assert retried.status_code == 200
    assert retried.json()["razorpayPlanId"] is not None
    assert await plan_count(admin) == 2


async def test_a_used_product_keeps_its_financial_fields(admin: BillingApi) -> None:
    pack = await created_product(admin, pack_body(f"used_{new_id().hex[-8:]}"))
    ordered = await admin.create_order(admin.primary, body={"productCode": pack["code"]})
    assert ordered.status_code == 201, ordered.text

    detail = (await get(admin, f"/products/{pack['id']}")).json()
    refused = await patch(admin, f"/products/{pack['id']}", {"version": 1, "pricePaise": 1_000})
    credit_edit = await patch(admin, f"/products/{pack['id']}", {"version": 1, "creditsGranted": 1})
    renamed = await patch(admin, f"/products/{pack['id']}", {"version": 1, "name": "Renamed", "sortOrder": 9})

    assert detail["isUsed"] is True
    assert (refused.status_code, refused.json()["code"]) == (409, "product_immutable")
    assert "Duplicate it as a new version" in refused.json()["detail"]
    assert refused.json()["fields"] == "price_paise"
    assert credit_edit.json()["code"] == "product_immutable"
    assert renamed.status_code == 200, renamed.text
    assert (renamed.json()["name"], renamed.json()["sortOrder"], renamed.json()["pricePaise"]) == (
        "Renamed",
        9,
        29_900,
    )
    assert renamed.json()["version"] == 2


async def test_the_database_trigger_still_guards_a_used_product(admin: BillingApi) -> None:
    pack = await created_product(admin, pack_body(f"trig_{new_id().hex[-8:]}"))
    await admin.create_order(admin.primary, body={"productCode": pack["code"]})

    with pytest.raises(IntegrityError, match="financially immutable"):
        async with admin.database.transaction() as session:
            await session.execute(
                text("UPDATE products SET price_paise = 1 WHERE code = :code"), {"code": pack["code"]}
            )


async def test_an_unused_product_can_change_money_and_every_edit_bumps_the_version(admin: BillingApi) -> None:
    pack = await created_product(admin, pack_body(f"free_{new_id().hex[-8:]}"))

    first = await patch(admin, f"/products/{pack['id']}", {"version": 1, "pricePaise": 31_000, "creditsGranted": 160})
    second = await patch(admin, f"/products/{pack['id']}", {"version": 2, "features": ["a", "b"], "description": None})

    assert (first.json()["version"], first.json()["pricePaise"], first.json()["creditsGranted"]) == (2, 31_000, 160)
    assert (second.json()["version"], second.json()["features"], second.json()["description"]) == (3, ["a", "b"], None)


async def test_a_synced_plan_is_unlinked_when_its_price_changes(admin: BillingApi) -> None:
    plan = await created_product(admin, plan_body(f"reprice_{new_id().hex[-6:]}"))
    await post(admin, f"/products/{plan['id']}/sync-plan")
    await post(admin, f"/products/{plan['id']}/activate")

    changed = await patch(admin, f"/products/{plan['id']}", {"version": 1, "pricePaise": 79_900})

    assert changed.status_code == 200, changed.text
    assert (changed.json()["razorpayPlanId"], changed.json()["isActive"]) == (None, False)


async def test_a_stale_version_is_a_conflict_and_concurrent_edits_cannot_both_win(admin: BillingApi) -> None:
    pack = await created_product(admin, pack_body(f"race_{new_id().hex[-8:]}"))
    path = f"/products/{pack['id']}"
    winner = await patch(admin, path, {"version": 1, "name": "Winner"})

    stale = await patch(admin, path, {"version": 1, "name": "Loser"})
    racers = await asyncio.gather(
        patch(admin, path, {"version": 2, "name": "A"}), patch(admin, path, {"version": 2, "name": "B"})
    )

    assert winner.status_code == 200
    assert (stale.status_code, stale.json()["code"]) == (409, "product_version_conflict")
    assert sorted(response.status_code for response in racers) == [200, 409]
    assert (await get(admin, path)).json()["version"] == 3


async def test_a_duplicate_code_is_a_conflict_and_bad_shapes_are_unprocessable(admin: BillingApi) -> None:
    code = f"dup_{new_id().hex[-8:]}"
    await created_product(admin, pack_body(code))

    again = await post(admin, "/products", pack_body(code))
    shapeless = await post(admin, "/products", plan_body(f"x_{new_id().hex[-8:]}", interval="month", planKey=None))
    pack_with_interval = await post(admin, "/products", pack_body(f"y_{new_id().hex[-8:]}", interval="month"))

    assert (again.status_code, again.json()["code"]) == (409, "product_code_exists")
    assert (shapeless.status_code, shapeless.json()["code"]) == (422, "invalid_product_shape")
    assert (pack_with_interval.status_code, pack_with_interval.json()["code"]) == (422, "invalid_product_shape")


async def test_requests_are_validated_and_unknown_products_are_missing(admin: BillingApi) -> None:
    bad: list[dict[str, Any]] = [
        pack_body("Bad Code"),
        pack_body("ok_code", pricePaise=0),
        pack_body("ok_code", extra="field"),
        pack_body("ok_code", features=["x"] * 21),
    ]
    responses = [await post(admin, "/products", body) for body in bad]
    empty = await patch(admin, f"/products/{UNKNOWN_ID}", {"version": 1})
    missing = await patch(admin, f"/products/{UNKNOWN_ID}", {"version": 1, "name": "x"})

    assert [response.status_code for response in responses] == [422] * len(bad)
    assert empty.status_code == 422
    assert (missing.status_code, missing.json()["code"]) == (404, "product_not_found")
    for action in ("activate", "deactivate", "duplicate", "sync-plan"):
        assert (await post(admin, f"/products/{UNKNOWN_ID}/{action}")).status_code == 404
    assert (await get(admin, f"/products/{UNKNOWN_ID}")).status_code == 404


async def test_product_writes_refresh_the_public_listing_and_queue_a_revalidation(admin: BillingApi) -> None:
    code = f"live_{new_id().hex[-8:]}"
    before = await public_codes(admin)
    assert code not in before
    revalidations = admin.recorded.revalidations

    pack = await created_product(admin, pack_body(code))
    assert code in await public_codes(admin)
    renamed = await patch(admin, f"/products/{pack['id']}", {"version": 1, "name": "Fresh name"})
    deactivated = await post(admin, f"/products/{pack['id']}/deactivate")
    await get(admin, "/products")

    assert renamed.status_code == deactivated.status_code == 200
    assert code not in await public_codes(admin)
    assert admin.recorded.revalidations == revalidations + 3


async def test_listing_filters_search_and_paginates(admin: BillingApi) -> None:
    marker = new_id().hex[-8:]
    for number in range(3):
        await created_product(admin, pack_body(f"list_{marker}_{number}", isActive=number != 1))
    await created_product(admin, plan_body(f"list_{marker}_plan"))

    searched = await listed(admin, "/products", search=f"LIST_{marker}")
    active_packs = await listed(admin, "/products", search=marker, kind="credit_pack", isActive="true")
    subscriptions = await listed(admin, "/products", search=marker, kind="subscription")
    first = (await get(admin, "/products", search=marker, limit=3)).json()
    rest = (await get(admin, "/products", search=marker, limit=3, cursor=first["nextCursor"])).json()
    forged = await get(admin, "/products", cursor="forged.cursor")

    assert len(searched) == 4
    assert {item["code"] for item in active_packs} == {f"list_{marker}_0", f"list_{marker}_2"}
    assert [item["kind"] for item in subscriptions] == ["subscription"]
    assert len(first["items"]) == 3
    assert len(rest["items"]) == 1
    assert rest["nextCursor"] is None
    assert forged.status_code == 422


async def test_the_repository_reports_trigger_and_index_violations_as_typed_errors(admin: BillingApi) -> None:
    pack = await created_product(admin, pack_body(f"repo_{new_id().hex[-8:]}"))
    await admin.create_order(admin.primary, body={"productCode": pack["code"]})
    plan_key = f"repo_{new_id().hex[-6:]}"
    first = await created_product(admin, plan_body(f"{plan_key}_a", plan_key=plan_key))
    second = await created_product(admin, plan_body(f"{plan_key}_b", plan_key=plan_key))
    for product in (first, second):
        await post(admin, f"/products/{product['id']}/sync-plan")
    await post(admin, f"/products/{first['id']}/activate")

    async with admin.database.transaction() as session:
        repository = SqlProductAdminRepository(session)
        with pytest.raises(ProductImmutableError):
            await repository.update_product(UUID(pack["id"]), 1, {"price_paise": 1})
        with pytest.raises(ActivePlanConflictError):
            await repository.set_active(UUID(second["id"]), active=True)
        with pytest.raises(ProductCodeExistsError):
            await repository.insert_product(
                NewProduct(
                    id=new_id(), code=pack["code"], kind="credit_pack", name="Clash", price_paise=100, credits_granted=1
                )
            )
        assert await repository.codes_with_prefix(plan_key) == {f"{plan_key}_a", f"{plan_key}_b"}
        assert await repository.active_product_code(plan_key, "month", UUID(second["id"])) == f"{plan_key}_a"
        assert await repository.active_product_code(plan_key, "month", UUID(first["id"])) is None
        assert await repository.set_plan_id(UUID(first["id"]), "plan_other") is False
