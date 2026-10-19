from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from tests.integration.billing_admin_support import UNKNOWN_ID, become, get, listed, post
from tests.integration.billing_support import PACK_CREDITS, BillingApi

CAPTURED_AND_PAID = ["payment.captured", "order.paid"]


@pytest.fixture
async def admin(billing_api: BillingApi) -> BillingApi:
    await become(billing_api, "admin")
    return billing_api


async def received_events(api: BillingApi) -> tuple[dict[str, Any], list[UUID]]:
    checkout = await api.checkout()
    await api.pay(checkout["razorpayOrderId"], webhooks=CAPTURED_AND_PAID)
    return checkout, [event.id for event in await api.event_rows()]


async def mark(api: BillingApi, event_id: UUID, status: str) -> None:
    async with api.database.transaction() as session:
        await session.execute(
            text("UPDATE webhook_events SET status = :status, attempts = 3, last_error = 'boom' WHERE id = :id"),
            {"status": status, "id": event_id},
        )


async def test_events_are_listed_without_payloads_and_filtered(admin: BillingApi) -> None:
    await received_events(admin)
    now = datetime.now(UTC)

    everything = await listed(admin, "/webhooks")
    captured = await listed(admin, "/webhooks", eventType="payment.captured")
    received = await listed(admin, "/webhooks", status="received")
    processed = await listed(admin, "/webhooks", status="processed")
    future = await listed(admin, "/webhooks", receivedFrom=(now + timedelta(hours=1)).isoformat())
    window = await listed(
        admin,
        "/webhooks",
        receivedFrom=(now - timedelta(hours=1)).isoformat(),
        receivedTo=(now + timedelta(hours=1)).isoformat(),
    )
    page = (await get(admin, "/webhooks", limit=1)).json()
    rest = (await get(admin, "/webhooks", limit=1, cursor=page["nextCursor"])).json()

    assert sorted(item["eventType"] for item in everything) == sorted(CAPTURED_AND_PAID)
    assert all("payload" not in item for item in everything)
    assert [item["eventType"] for item in captured] == ["payment.captured"]
    assert len(received) == 2
    assert processed == []
    assert future == []
    assert len(window) == 2
    assert page["nextCursor"] is not None
    assert rest["nextCursor"] is None
    assert page["items"][0]["id"] != rest["items"][0]["id"]
    assert set(everything[0]) == {
        "id",
        "provider",
        "eventId",
        "eventType",
        "eventCreatedAt",
        "status",
        "attempts",
        "lastError",
        "ignoredReason",
        "receivedAt",
        "processedAt",
    }


async def test_an_event_detail_includes_its_payload(admin: BillingApi) -> None:
    _, [event_id, _] = await received_events(admin)

    detail = (await get(admin, f"/webhooks/{event_id}")).json()
    missing = await get(admin, f"/webhooks/{UNKNOWN_ID}")

    assert detail["id"] == str(event_id)
    assert detail["provider"] == "razorpay"
    assert detail["payload"]["event"] in CAPTURED_AND_PAID
    assert "payload" in detail["payload"]
    assert (missing.status_code, missing.json()["code"]) == (404, "webhook_event_not_found")


async def test_reprocessing_a_failed_event_settles_the_order(admin: BillingApi) -> None:
    checkout, [event_id, other_id] = await received_events(admin)
    admin.recorded.dispatched.clear()
    await mark(admin, event_id, "failed")
    await mark(admin, other_id, "failed")

    response = await post(admin, f"/webhooks/{event_id}/reprocess")

    assert response.status_code == 202, response.text
    assert response.json() == {"id": str(event_id), "previousStatus": "failed", "queued": True}
    assert admin.recorded.dispatched == [(event_id, True)]
    assert (await admin.order_row(checkout["orderId"])).status != "paid"
    await admin.process_dispatched()
    assert (await admin.order_row(checkout["orderId"])).status == "paid"
    assert await admin.wallet_balance(admin.primary_id) == PACK_CREDITS
    settled = (await get(admin, f"/webhooks/{event_id}")).json()
    assert settled["status"] == "processed"
    assert "billing.webhook.reprocess_requested" in await admin.audit_actions()


@pytest.mark.parametrize("status", ["processed", "ignored"])
async def test_a_finished_event_can_be_replayed_without_double_crediting(admin: BillingApi, status: str) -> None:
    checkout, [event_id, _] = await received_events(admin)
    await admin.process_dispatched()
    await mark(admin, event_id, status)
    admin.recorded.dispatched.clear()

    response = await post(admin, f"/webhooks/{event_id}/reprocess")
    await admin.process_dispatched()

    assert response.status_code == 202
    assert response.json()["previousStatus"] == status
    assert (await admin.order_row(checkout["orderId"])).status == "paid"
    assert await admin.wallet_balance(admin.primary_id) == PACK_CREDITS
    assert len(await admin.ledger_rows(admin.primary_id)) == 1


@pytest.mark.parametrize("status", ["received", "processing"])
async def test_an_event_that_is_still_in_flight_cannot_be_reprocessed(admin: BillingApi, status: str) -> None:
    _, [event_id, _] = await received_events(admin)
    await mark(admin, event_id, status)
    admin.recorded.dispatched.clear()

    response = await post(admin, f"/webhooks/{event_id}/reprocess")

    assert (response.status_code, response.json()["code"]) == (409, "webhook_event_not_reprocessable")
    assert admin.recorded.dispatched == []


async def test_reprocessing_an_unknown_event_is_missing(admin: BillingApi) -> None:
    response = await post(admin, f"/webhooks/{UNKNOWN_ID}/reprocess")

    assert (response.status_code, response.json()["code"]) == (404, "webhook_event_not_found")
