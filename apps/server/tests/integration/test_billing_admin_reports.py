import json
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text
from tests.integration.billing_admin_support import UNKNOWN_ID, become, get, listed, post
from tests.integration.billing_support import (
    PACK_CREDITS,
    PACK_PRICE,
    SUBSCRIPTION_CREDITS,
    SUBSCRIPTION_PRICE,
    BillingApi,
)
from tests.integration.test_billing_refunds import paid_pack, process_refund, refund_via_api, spend

from motionile.core.ids import new_id


@pytest.fixture
async def admin(billing_api: BillingApi) -> BillingApi:
    await become(billing_api, "super_admin")
    return billing_api


async def insert_run(api: BillingApi, run_type: str, status: str, mismatches: int = 0) -> str:
    run_id = new_id()
    async with api.database.transaction() as session:
        await session.execute(
            text(
                "INSERT INTO billing_reconciliation_runs "
                "(id, type, status, checked_count, repaired_count, mismatch_count, summary, error, "
                "started_at, finished_at) "
                "VALUES (:id, :type, :status, 10, 1, :mismatches, CAST(:summary AS jsonb), :error, now(), "
                "CASE WHEN :status = 'running' THEN NULL ELSE now() END)"
            ),
            {
                "id": run_id,
                "type": run_type,
                "status": status,
                "mismatches": mismatches,
                "summary": json.dumps({"mismatched": mismatches}),
                "error": "failed hard" if status == "failed" else None,
            },
        )
    return str(run_id)


async def settlement_run(api: BillingApi) -> dict[str, Any]:
    await paid_pack(api)
    async with api.database.transaction() as session:
        await session.execute(text("UPDATE payments SET created_at = :now"), {"now": api.clock.now()})
    result = await api.services.settlement_check.run(api.clock.now().date())
    assert result is not None
    [run] = await api.run_rows("settlement")
    return {"id": str(run.id), "key": run.report_storage_key}


async def test_runs_are_listed_and_filtered(admin: BillingApi) -> None:
    clean = await insert_run(admin, "subscriptions", "completed")
    dirty = await insert_run(admin, "pending_orders", "completed", mismatches=2)
    broken = await insert_run(admin, "settlement", "failed")
    running = await insert_run(admin, "subscriptions", "running")

    everything = await listed(admin, "/reconciliation/runs")
    subscriptions = await listed(admin, "/reconciliation/runs", type="subscriptions")
    failed = await listed(admin, "/reconciliation/runs", status="failed")
    mismatched = await listed(admin, "/reconciliation/runs", hasMismatches="true")
    clear = await listed(admin, "/reconciliation/runs", hasMismatches="false", type="subscriptions")
    page = (await get(admin, "/reconciliation/runs", limit=3)).json()
    rest = (await get(admin, "/reconciliation/runs", limit=3, cursor=page["nextCursor"])).json()

    assert [item["id"] for item in everything] == [running, broken, dirty, clean]
    assert {item["id"] for item in subscriptions} == {clean, running}
    assert [item["id"] for item in failed] == [broken]
    assert [item["id"] for item in mismatched] == [dirty]
    assert {item["id"] for item in clear} == {clean, running}
    assert (len(page["items"]), len(rest["items"]), rest["nextCursor"]) == (3, 1, None)


async def test_a_run_shows_its_counts_summary_and_error(admin: BillingApi) -> None:
    run_id = await insert_run(admin, "settlement", "failed", mismatches=3)

    run = (await get(admin, f"/reconciliation/runs/{run_id}")).json()
    missing = await get(admin, f"/reconciliation/runs/{UNKNOWN_ID}")

    assert (run["type"], run["status"], run["checkedCount"], run["repairedCount"], run["mismatchCount"]) == (
        "settlement",
        "failed",
        10,
        1,
        3,
    )
    assert (run["summary"], run["error"], run["hasReport"]) == ({"mismatched": 3}, "failed hard", False)
    assert run["finishedAt"] is not None
    assert "reportStorageKey" not in run
    assert (missing.status_code, missing.json()["code"]) == (404, "reconciliation_run_not_found")


async def test_a_stored_report_is_downloaded_as_an_attachment(admin: BillingApi) -> None:
    run = await settlement_run(admin)

    response = await get(admin, f"/reconciliation/runs/{run['id']}/report")
    detail = (await get(admin, f"/reconciliation/runs/{run['id']}")).json()

    assert response.status_code == 200, response.text
    assert response.content == admin.storage.objects[run["key"]].data
    assert response.headers["content-type"].startswith("application/json")
    assert (
        response.headers["content-disposition"] == f'attachment; filename="reconciliation-settlement-{run["id"]}.json"'
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-length"] == str(len(response.content))
    assert response.json()["counts"]["checked"] == 1
    assert detail["hasReport"] is True


async def test_a_run_without_a_report_or_with_a_vanished_object_has_nothing_to_download(admin: BillingApi) -> None:
    bare = await insert_run(admin, "subscriptions", "completed")
    run = await settlement_run(admin)
    del admin.storage.objects[run["key"]]

    without_report = await get(admin, f"/reconciliation/runs/{bare}/report")
    without_object = await get(admin, f"/reconciliation/runs/{run['id']}/report")
    unknown = await get(admin, f"/reconciliation/runs/{UNKNOWN_ID}/report")

    assert (without_report.status_code, without_report.json()["code"]) == (404, "reconciliation_report_not_found")
    assert without_object.status_code == 404
    assert unknown.json()["code"] == "reconciliation_run_not_found"


async def test_revenue_is_zero_filled_and_nets_refunds(admin: BillingApi) -> None:
    payment_id = await paid_pack(admin)
    refund = await refund_via_api(admin, payment_id, 5_000)
    await process_refund(admin, refund)
    today = admin.clock.now().date()

    report = (await get(admin, "/analytics/revenue", **{"from": (today - timedelta(days=2)).isoformat()})).json()
    default = (await get(admin, "/analytics/revenue")).json()

    assert report["currency"] == "INR"
    assert [day["date"] for day in report["days"]] == [
        (today - timedelta(days=offset)).isoformat() for offset in (2, 1, 0)
    ]
    assert report["days"][:2] == [
        {"date": report["days"][0]["date"], "capturedPaise": 0, "refundedPaise": 0, "netPaise": 0, "paymentCount": 0},
        {"date": report["days"][1]["date"], "capturedPaise": 0, "refundedPaise": 0, "netPaise": 0, "paymentCount": 0},
    ]
    assert report["days"][2] == {
        "date": today.isoformat(),
        "capturedPaise": PACK_PRICE,
        "refundedPaise": 5_000,
        "netPaise": PACK_PRICE - 5_000,
        "paymentCount": 1,
    }
    assert report["totals"] == {
        "capturedPaise": PACK_PRICE,
        "refundedPaise": 5_000,
        "netPaise": PACK_PRICE - 5_000,
        "paymentCount": 1,
    }
    assert len(default["days"]) == 30
    assert default["rangeEnd"] == today.isoformat()


async def test_a_pending_refund_is_not_revenue_loss_yet(admin: BillingApi) -> None:
    payment_id = await paid_pack(admin)
    await refund_via_api(admin, payment_id, 5_000)

    report = (await get(admin, "/analytics/revenue")).json()

    assert report["totals"]["refundedPaise"] == 0
    assert report["totals"]["capturedPaise"] == PACK_PRICE


async def test_subscription_analytics_count_live_subscriptions_by_plan(admin: BillingApi) -> None:
    pro = await admin.plan_product()
    await admin.activate_subscription(pro, admin.other)
    ended = await admin.plan_product()
    started = await admin.activate_subscription(ended)
    await post(admin, f"/subscriptions/{started['subscriptionId']}/cancel", {"immediately": True})

    report = (await get(admin, "/analytics/subscriptions")).json()

    assert report["totalLive"] == 1
    assert report["totalActive"] == 1
    [plan] = report["byPlan"]
    assert (plan["planKey"], plan["productCode"], plan["interval"], plan["liveCount"], plan["activeCount"]) == (
        f"{pro}_plan",
        pro,
        "month",
        1,
        1,
    )
    assert report["byStatus"] == {
        "created": 0,
        "authenticated": 0,
        "active": 1,
        "pending": 0,
        "halted": 0,
        "paused": 0,
        "cancelled": 1,
        "completed": 0,
        "expired": 0,
    }


async def test_credit_analytics_split_grants_consumption_and_clawbacks(admin: BillingApi) -> None:
    payment_id = await paid_pack(admin)
    await spend(admin, 30)
    refund = await refund_via_api(admin, payment_id, 5_000)
    await process_refund(admin, refund)
    code = await admin.plan_product()
    await admin.activate_subscription(code, admin.other)
    await post(admin, f"/users/{admin.primary_id}/credits/adjust", {"delta": 10, "reason": "Goodwill"})
    await post(admin, f"/users/{admin.primary_id}/credits/adjust", {"delta": -5, "reason": "Correction"})
    today = admin.clock.now().date()

    report = (await get(admin, "/analytics/credits", **{"from": today.isoformat(), "to": today.isoformat()})).json()

    [day] = report["days"]
    assert day["date"] == today.isoformat()
    assert day["granted"] == {"purchase": PACK_CREDITS, "subscription": SUBSCRIPTION_CREDITS, "promo": 0, "admin": 10}
    assert day["grantedTotal"] == PACK_CREDITS + SUBSCRIPTION_CREDITS + 10
    assert (day["consumed"], day["expired"], day["clawedBack"], day["adjustedDown"]) == (30, 0, 26, 5)
    assert report["totals"] == {
        "granted": day["granted"],
        "grantedTotal": day["grantedTotal"],
        "consumed": 30,
        "expired": 0,
        "clawedBack": 26,
        "adjustedDown": 5,
    }
    primary_balance = PACK_CREDITS - 30 - 26 + 10 - 5
    assert (report["wallets"], report["reserved"]) == (2, 0)
    assert report["balance"] == primary_balance + SUBSCRIPTION_CREDITS


async def test_analytics_ranges_are_bounded(admin: BillingApi) -> None:
    today = admin.clock.now().date()
    longest = today - timedelta(days=365)
    too_long = today - timedelta(days=366)

    for path in ("/analytics/revenue", "/analytics/credits"):
        ok = await get(admin, path, **{"from": longest.isoformat()})
        long = await get(admin, path, **{"from": too_long.isoformat()})
        inverted = await get(admin, path, **{"from": today.isoformat(), "to": (today - timedelta(days=1)).isoformat()})
        malformed = await get(admin, path, **{"from": "yesterday"})
        extra = await get(admin, path, days=7)

        assert ok.status_code == 200
        assert len(ok.json()["days"]) == 366
        assert (long.status_code, long.json()["code"]) == (422, "invalid_analytics_range")
        assert inverted.json()["code"] == "invalid_analytics_range"
        assert malformed.status_code == 422
        assert extra.status_code == 422


async def test_subscription_prices_are_not_confused_with_pack_prices(admin: BillingApi) -> None:
    code = await admin.plan_product()
    await admin.activate_subscription(code, admin.other)

    report = (await get(admin, "/analytics/revenue")).json()

    assert report["totals"]["capturedPaise"] == SUBSCRIPTION_PRICE
    assert report["totals"]["paymentCount"] == 1
