import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from tests.integration.billing_admin_support import UNKNOWN_ID, become, get, listed, post
from tests.integration.billing_support import PACK_CREDITS, BillingApi
from tests.integration.test_billing_refunds import paid_pack

from motionile.core.ids import new_id
from motionile.modules.credits import ReserveCommand


@pytest.fixture
async def admin(billing_api: BillingApi) -> BillingApi:
    await become(billing_api, "super_admin")
    return billing_api


def credits_path(api: BillingApi, suffix: str = "") -> str:
    return f"/users/{api.primary_id}/credits{suffix}"


async def adjust(api: BillingApi, delta: int, key: str | None = None, **body: Any) -> Any:
    return await post(
        api, credits_path(api, "/adjust"), {"delta": delta, "reason": "Support goodwill", **body}, key=key
    )


async def ledger_count(api: BillingApi) -> int:
    return len(await api.ledger_rows(api.primary_id))


async def test_a_wallet_view_shows_balances_and_lots(admin: BillingApi) -> None:
    await paid_pack(admin)

    view = (await get(admin, credits_path(admin))).json()

    assert (view["userId"], view["balance"], view["reserved"], view["available"]) == (
        str(admin.primary_id),
        PACK_CREDITS,
        0,
        PACK_CREDITS,
    )
    [lot] = view["lots"]
    assert (lot["source"], lot["amount"], lot["remaining"], lot["expiresAt"], lot["refType"]) == (
        "purchase",
        PACK_CREDITS,
        PACK_CREDITS,
        None,
        "payment",
    )
    assert view["nextCursor"] is None


async def test_held_credits_reduce_what_is_available(admin: BillingApi) -> None:
    await paid_pack(admin)
    async with admin.database.transaction() as session:
        await admin.credits.reserve(
            session,
            ReserveCommand(user_id=admin.primary_id, amount=30, ref_type="job", ref_id=new_id(), key="hold-1"),
        )

    view = (await get(admin, credits_path(admin))).json()

    assert (view["balance"], view["reserved"], view["available"]) == (PACK_CREDITS, 30, PACK_CREDITS - 30)


async def test_a_user_without_a_wallet_has_an_empty_one_and_an_unknown_user_is_missing(admin: BillingApi) -> None:
    empty = (await get(admin, f"/users/{admin.other_id}/credits")).json()
    ledger = (await get(admin, f"/users/{admin.other_id}/credits/ledger")).json()
    unknown = await get(admin, f"/users/{UNKNOWN_ID}/credits")
    unknown_ledger = await get(admin, f"/users/{UNKNOWN_ID}/credits/ledger")

    assert (empty["balance"], empty["available"], empty["lots"]) == (0, 0, [])
    assert ledger["items"] == []
    assert (unknown.status_code, unknown.json()["code"]) == (404, "user_not_found")
    assert unknown_ledger.status_code == 404


async def test_a_grant_creates_a_lot_a_ledger_row_and_an_audit_entry(admin: BillingApi) -> None:
    await paid_pack(admin)
    expires = (datetime.now(UTC) + timedelta(days=30)).replace(microsecond=0)

    response = await adjust(admin, 50, expiresAt=expires.isoformat())

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["userId"], body["delta"], body["balanceAfter"]) == (str(admin.primary_id), 50, PACK_CREDITS + 50)
    assert body["lotId"] is not None
    assert await admin.wallet_balance(admin.primary_id) == PACK_CREDITS + 50
    lots = (await get(admin, credits_path(admin))).json()["lots"]
    granted = next(lot for lot in lots if lot["source"] == "admin")
    assert (granted["amount"], granted["remaining"], granted["refType"]) == (50, 50, "admin")
    assert datetime.fromisoformat(granted["expiresAt"]) == expires
    entries = await listed(admin, credits_path(admin, "/ledger"))
    latest = entries[0]
    assert (latest["reason"], latest["delta"], latest["balanceAfter"], latest["refType"]) == (
        "admin_adjust",
        50,
        PACK_CREDITS + 50,
        "admin",
    )
    assert latest["metadata"]["reason"] == "Support goodwill"
    assert latest["metadata"]["actorId"] == str(admin.other_id)
    assert latest["idempotencyKey"].startswith("admin-adjust:")
    async with admin.database.transaction() as session:
        row = (
            await session.execute(
                text("SELECT actor_user_id, target_id, metadata FROM audit_log WHERE action = 'credits.adjusted'")
            )
        ).one()
    assert (row[0], row[1], row[2]["delta"], row[2]["reason"]) == (
        admin.other_id,
        str(admin.primary_id),
        50,
        "Support goodwill",
    )


async def test_a_deduction_consumes_lots_and_never_goes_below_available(admin: BillingApi) -> None:
    await paid_pack(admin)

    removed = await adjust(admin, -40)
    refused = await adjust(admin, -61)

    assert removed.status_code == 201, removed.text
    assert (removed.json()["delta"], removed.json()["balanceAfter"], removed.json()["lotId"]) == (
        -40,
        PACK_CREDITS - 40,
        None,
    )
    assert (refused.status_code, refused.json()["code"]) == (409, "adjustment_exceeds_available")
    assert await admin.wallet_balance(admin.primary_id) == PACK_CREDITS - 40
    assert (await admin.lot_rows())[0][2] == PACK_CREDITS - 40


async def test_credits_held_by_a_reservation_cannot_be_adjusted_away(admin: BillingApi) -> None:
    await paid_pack(admin)
    async with admin.database.transaction() as session:
        await admin.credits.reserve(
            session,
            ReserveCommand(user_id=admin.primary_id, amount=80, ref_type="job", ref_id=new_id(), key="hold-2"),
        )

    refused = await adjust(admin, -30)
    allowed = await adjust(admin, -20)

    assert refused.json()["code"] == "adjustment_exceeds_available"
    assert allowed.status_code == 201


async def test_a_retried_adjustment_replays_the_first_answer(admin: BillingApi) -> None:
    await paid_pack(admin)
    key = admin.keys()

    first = await adjust(admin, 25, key)
    replayed = await adjust(admin, 25, key)
    reused = await adjust(admin, 26, key)

    assert first.status_code == 201
    assert replayed.headers["idempotent-replayed"] == "true"
    assert replayed.json() == first.json()
    assert (reused.status_code, reused.json()["code"]) == (409, "idempotency_key_reused")
    assert await ledger_count(admin) == 2
    assert await admin.wallet_balance(admin.primary_id) == PACK_CREDITS + 25


async def test_a_key_cannot_be_reused_for_another_target(admin: BillingApi) -> None:
    key = admin.keys()

    first = await post(admin, credits_path(admin, "/adjust"), {"delta": 5, "reason": "A"}, key=key)
    second = await post(admin, f"/users/{admin.other_id}/credits/adjust", {"delta": 5, "reason": "A"}, key=key)

    assert first.status_code == 201
    assert (second.status_code, second.json()["code"]) == (409, "idempotency_key_reused")
    assert await admin.wallet_balance(admin.other_id) == 0


async def test_concurrent_deductions_cannot_overdraw_the_wallet(admin: BillingApi) -> None:
    await paid_pack(admin)

    responses = await asyncio.gather(adjust(admin, -60), adjust(admin, -60), adjust(admin, -60))

    assert sorted(response.status_code for response in responses) == [201, 409, 409]
    assert await admin.wallet_balance(admin.primary_id) == PACK_CREDITS - 60
    assert await ledger_count(admin) == 2


async def test_concurrent_grants_all_land(admin: BillingApi) -> None:
    responses = await asyncio.gather(*[adjust(admin, 10) for _ in range(4)])

    assert [response.status_code for response in responses] == [201] * 4
    assert await admin.wallet_balance(admin.primary_id) == 40


async def test_adjustments_to_unknown_users_are_missing(admin: BillingApi) -> None:
    grant = await post(admin, f"/users/{UNKNOWN_ID}/credits/adjust", {"delta": 5, "reason": "x"})
    deduction = await post(admin, f"/users/{UNKNOWN_ID}/credits/adjust", {"delta": -5, "reason": "x"})

    assert (grant.status_code, grant.json()["code"]) == (404, "user_not_found")
    assert deduction.status_code == 404


async def test_adjustment_requests_are_validated(admin: BillingApi) -> None:
    await paid_pack(admin)
    bad: list[dict[str, Any]] = [
        {"delta": 0, "reason": "zero"},
        {"delta": 1_000_001, "reason": "huge"},
        {"delta": 1.5, "reason": "fraction"},
        {"delta": 5, "reason": ""},
        {"delta": 5, "reason": "x" * 501},
        {"delta": 5},
        {"reason": "no delta"},
        {"delta": 5, "reason": "ok", "userId": str(admin.other_id)},
        {"delta": 5, "reason": "ok", "expiresAt": "2030-01-01T00:00:00"},
    ]
    responses = [await post(admin, credits_path(admin, "/adjust"), body) for body in bad]
    past = await adjust(admin, 5, expiresAt=(datetime.now(UTC) - timedelta(days=1)).isoformat())
    deduction_with_expiry = await adjust(admin, -5, expiresAt=(datetime.now(UTC) + timedelta(days=1)).isoformat())
    without_key = {k: v for k, v in admin.headers(admin.other).items() if k.lower() != "idempotency-key"}
    no_key = await admin.other.post(
        f"/v1/admin/billing{credits_path(admin, '/adjust')}", json={"delta": 5, "reason": "ok"}, headers=without_key
    )

    assert [response.status_code for response in responses] == [422] * len(bad)
    assert (past.status_code, past.json()["code"]) == (422, "invalid_credit_expiry")
    assert deduction_with_expiry.status_code == 422
    assert no_key.status_code == 400
    assert await ledger_count(admin) == 1


async def test_the_ledger_is_paged_newest_first_with_full_fields(admin: BillingApi) -> None:
    await paid_pack(admin)
    for amount in (5, 6, 7):
        assert (await adjust(admin, amount)).status_code == 201

    first = (await get(admin, credits_path(admin, "/ledger"), limit=2)).json()
    rest = (await get(admin, credits_path(admin, "/ledger"), limit=2, cursor=first["nextCursor"])).json()
    forged = await get(admin, credits_path(admin, "/ledger"), cursor="forged.cursor")

    assert [item["delta"] for item in first["items"]] == [7, 6]
    assert [item["delta"] for item in rest["items"]] == [5, PACK_CREDITS]
    assert rest["nextCursor"] is None
    assert set(first["items"][0]) == {
        "id",
        "reason",
        "delta",
        "reservedDelta",
        "balanceAfter",
        "reservedAfter",
        "refType",
        "refId",
        "idempotencyKey",
        "metadata",
        "createdAt",
    }
    assert forged.status_code == 422


async def test_lots_are_paged(admin: BillingApi) -> None:
    for amount in (5, 6, 7):
        await adjust(admin, amount)

    first = (await get(admin, credits_path(admin), limit=2)).json()
    rest = (await get(admin, credits_path(admin), limit=2, cursor=first["nextCursor"])).json()

    assert [lot["amount"] for lot in first["lots"]] == [7, 6]
    assert [lot["amount"] for lot in rest["lots"]] == [5]
    assert rest["nextCursor"] is None
