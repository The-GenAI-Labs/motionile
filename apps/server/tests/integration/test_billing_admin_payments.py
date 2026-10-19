from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from tests.integration.billing_admin_support import UNKNOWN_ID, become, get, listed, post
from tests.integration.billing_support import PACK_CREDITS, PACK_PRICE, SUBSCRIPTION_CREDITS, BillingApi
from tests.integration.test_billing_refunds import paid_pack, process_refund, refund_via_api, spend


@pytest.fixture
async def admin(billing_api: BillingApi) -> BillingApi:
    await become(billing_api, "super_admin")
    return billing_api


async def payment_detail(api: BillingApi, payment_id: UUID | str, **params: int) -> dict[str, Any]:
    response = await get(api, f"/payments/{payment_id}", **params)
    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    return payload


async def test_a_payment_detail_shows_its_order_lot_refundable_amount_and_clawback_preview(admin: BillingApi) -> None:
    payment_id = await paid_pack(admin)

    detail = await payment_detail(admin, payment_id)

    assert detail["status"] == "captured"
    assert (detail["creditsGranted"], detail["refundablePaise"], detail["pendingRefundPaise"]) == (
        PACK_CREDITS,
        PACK_PRICE,
        0,
    )
    assert detail["clawbackPreview"] == {"amountPaise": PACK_PRICE, "creditsToClawBack": PACK_CREDITS}
    assert detail["userId"] == str(admin.primary_id)
    assert detail["productCode"] == admin.pack_code
    order = detail["order"]
    assert (order["status"], order["amountPaise"], order["flaggedAt"]) == ("paid", PACK_PRICE, None)
    lot = detail["lot"]
    assert (lot["source"], lot["amount"], lot["remaining"], lot["expiresAt"]) == ("purchase", 100, 100, None)
    assert detail["refunds"] == []
    assert detail["subscription"] is None


async def test_the_clawback_preview_is_the_amount_processing_then_claws_back(admin: BillingApi) -> None:
    payment_id = await paid_pack(admin)
    await spend(admin, 80)
    half = PACK_PRICE // 2

    preview = (await payment_detail(admin, payment_id, amountPaise=half))["clawbackPreview"]
    refund = await refund_via_api(admin, payment_id, half)
    await process_refund(admin, refund)

    assert preview == {"amountPaise": half, "creditsToClawBack": 20}
    [row] = await admin.refund_rows()
    assert row.credits_clawed_back == 20
    after = await payment_detail(admin, payment_id)
    assert after["refundablePaise"] == PACK_PRICE - half
    assert after["clawbackPreview"] == {"amountPaise": PACK_PRICE - half, "creditsToClawBack": 0}


@pytest.mark.parametrize("amount", [1, 5_000, 9_950, 13_333, PACK_PRICE])
async def test_the_preview_matches_the_rounding_of_the_processed_clawback(admin: BillingApi, amount: int) -> None:
    payment_id = await paid_pack(admin)

    preview = (await payment_detail(admin, payment_id, amountPaise=amount))["clawbackPreview"]
    refund = await refund_via_api(admin, payment_id, amount)
    await process_refund(admin, refund)

    [row] = await admin.refund_rows()
    assert preview == {"amountPaise": amount, "creditsToClawBack": row.credits_clawed_back}


async def test_a_payment_detail_lists_its_refunds_and_pending_amounts(admin: BillingApi) -> None:
    payment_id = await paid_pack(admin)
    refund = await refund_via_api(admin, payment_id, 4_000)

    detail = await payment_detail(admin, payment_id)

    assert detail["pendingRefundPaise"] == 4_000
    assert detail["refundablePaise"] == PACK_PRICE - 4_000
    [listed_refund] = detail["refunds"]
    assert (listed_refund["id"], listed_refund["status"], listed_refund["amountPaise"]) == (
        refund["id"],
        "pending",
        4_000,
    )


async def test_a_preview_above_the_refundable_amount_and_unknown_payments_are_refused(admin: BillingApi) -> None:
    payment_id = await paid_pack(admin)

    over = await get(admin, f"/payments/{payment_id}", amountPaise=PACK_PRICE + 1)
    zero = await get(admin, f"/payments/{payment_id}", amountPaise=0)
    unknown = await get(admin, f"/payments/{UNKNOWN_ID}")

    assert (over.status_code, over.json()["code"], over.json()["refundablePaise"]) == (
        422,
        "refund_exceeds_refundable",
        PACK_PRICE,
    )
    assert zero.status_code == 422
    assert (unknown.status_code, unknown.json()["code"]) == (404, "payment_not_found")


async def test_payments_are_filtered_and_paginated(admin: BillingApi) -> None:
    first = await paid_pack(admin)
    checkout = await admin.checkout(admin.other)
    paid = await admin.pay(checkout["razorpayOrderId"])
    verified = await admin.verify(paid, admin.other)
    assert verified.status_code == 200
    now = datetime.now(UTC)

    everyone = await listed(admin, "/payments")
    mine = await listed(admin, "/payments", userId=str(admin.primary_id))
    by_order = await listed(admin, "/payments", orderId=checkout["orderId"])
    captured = await listed(admin, "/payments", status="captured")
    failed = await listed(admin, "/payments", status="failed")
    future = await listed(admin, "/payments", createdFrom=(now + timedelta(hours=1)).isoformat())
    window = await listed(
        admin,
        "/payments",
        createdFrom=(now - timedelta(hours=1)).isoformat(),
        createdTo=(now + timedelta(hours=1)).isoformat(),
    )
    page = (await get(admin, "/payments", limit=1)).json()
    rest = (await get(admin, "/payments", limit=1, cursor=page["nextCursor"])).json()

    assert len(everyone) == 2
    assert [item["id"] for item in mine] == [str(first)]
    assert [item["orderId"] for item in by_order] == [checkout["orderId"]]
    assert len(captured) == 2
    assert failed == []
    assert future == []
    assert len(window) == 2
    assert len(page["items"]) == len(rest["items"]) == 1
    assert page["items"][0]["id"] != rest["items"][0]["id"]
    assert rest["nextCursor"] is None


async def test_a_flagged_order_and_its_payment_show_up_for_review(admin: BillingApi) -> None:
    clean = await admin.checkout()
    clean_paid = await admin.pay(clean["razorpayOrderId"])
    await admin.verify(clean_paid)
    flagged = await admin.checkout()
    mismatched = await admin.pay(flagged["razorpayOrderId"], amountPaise=PACK_PRICE - 1_000)
    await admin.verify(mismatched)

    flagged_orders = await listed(admin, "/orders", flagged="true")
    unflagged_orders = await listed(admin, "/orders", flagged="false")
    flagged_payments = await listed(admin, "/payments", flagged="true")
    detail = (await get(admin, f"/orders/{flagged['orderId']}")).json()
    pending = await listed(admin, "/orders", status="pending", userId=str(admin.primary_id))

    assert [item["id"] for item in flagged_orders] == [flagged["orderId"]]
    assert (flagged_orders[0]["flagReason"], flagged_orders[0]["flaggedAt"] is not None) == ("amount_mismatch", True)
    assert [item["id"] for item in unflagged_orders] == [clean["orderId"]]
    assert [item["amountPaise"] for item in flagged_payments] == [PACK_PRICE - 1_000]
    assert flagged_payments[0]["flagged"] is True
    assert flagged_payments[0]["creditsGranted"] == 0
    assert detail["status"] == "pending"
    assert [payment["razorpayPaymentId"] for payment in detail["payments"]] == [mismatched["razorpay_payment_id"]]
    assert [item["id"] for item in pending] == [flagged["orderId"]]
    assert (await get(admin, f"/orders/{UNKNOWN_ID}")).json()["code"] == "order_not_found"


async def test_refunds_are_listed_filtered_and_readable(admin: BillingApi) -> None:
    payment_id = await paid_pack(admin)
    first = await refund_via_api(admin, payment_id, 5_000)
    second = await refund_via_api(admin, payment_id, 3_000)
    await process_refund(admin, first)

    everything = await listed(admin, "/refunds")
    processed = await listed(admin, "/refunds", status="processed")
    pending = await listed(admin, "/refunds", status="pending")
    by_payment = await listed(admin, "/refunds", paymentId=str(payment_id))
    elsewhere = await listed(admin, "/refunds", paymentId=UNKNOWN_ID)
    detail = (await get(admin, f"/refunds/{first['id']}")).json()
    missing = await get(admin, f"/refunds/{UNKNOWN_ID}")

    assert [item["id"] for item in everything] == [second["id"], first["id"]]
    assert [item["id"] for item in processed] == [first["id"]]
    assert [item["id"] for item in pending] == [second["id"]]
    assert len(by_payment) == 2
    assert elsewhere == []
    assert (detail["status"], detail["amountPaise"], detail["creditsClawedBack"], detail["reason"]) == (
        "processed",
        5_000,
        26,
        "Customer asked for it",
    )
    assert (detail["userId"], detail["initiatedBy"], detail["paymentAmountPaise"]) == (
        str(admin.primary_id),
        str(admin.other_id),
        PACK_PRICE,
    )
    assert (missing.status_code, missing.json()["code"]) == (404, "refund_not_found")


async def test_subscriptions_are_listed_with_their_payments_and_orders(admin: BillingApi) -> None:
    code = await admin.plan_product()
    started = await admin.activate_subscription(code)
    subscription_id = started["subscriptionId"]

    everything = await listed(admin, "/subscriptions")
    active = await listed(admin, "/subscriptions", status="active", userId=str(admin.primary_id))
    ended = await listed(admin, "/subscriptions", status="cancelled")
    by_plan = await listed(admin, "/subscriptions", planKey=f"{code}_plan")
    other_plan = await listed(admin, "/subscriptions", planKey="nothing")
    detail = (await get(admin, f"/subscriptions/{subscription_id}")).json()
    [payment] = await admin.payment_rows()
    payment_view = await payment_detail(admin, payment.id)

    assert [item["id"] for item in everything] == [subscription_id]
    assert [item["id"] for item in active] == [subscription_id]
    assert ended == []
    assert [item["id"] for item in by_plan] == [subscription_id]
    assert other_plan == []
    assert (detail["status"], detail["userId"], detail["product"]["code"]) == (
        "active",
        str(admin.primary_id),
        code,
    )
    assert detail["pendingProduct"] is None
    assert [item["id"] for item in detail["payments"]] == [str(payment.id)]
    assert [item["kind"] for item in detail["orders"]] == ["subscription"]
    subscription = payment_view["subscription"]
    assert (subscription["id"], subscription["status"], subscription["productCode"]) == (
        subscription_id,
        "active",
        code,
    )
    assert payment_view["creditsGranted"] == SUBSCRIPTION_CREDITS
    assert (await get(admin, f"/subscriptions/{UNKNOWN_ID}")).json()["code"] == "subscription_not_found"


async def test_an_admin_cancels_at_the_period_end_and_then_immediately_without_refunds(admin: BillingApi) -> None:
    code = await admin.plan_product()
    started = await admin.activate_subscription(code)
    path = f"/subscriptions/{started['subscriptionId']}/cancel"

    scheduled = await post(admin, path, {"immediately": False})
    repeated = await post(admin, path, {"immediately": False})
    ended = await post(admin, path, {"immediately": True})
    again = await post(admin, path, {"immediately": True})

    assert scheduled.status_code == 200, scheduled.text
    assert (scheduled.json()["status"], scheduled.json()["cancelAtPeriodEnd"]) == ("active", True)
    assert repeated.json()["status"] == "active"
    assert (ended.status_code, ended.json()["status"]) == (200, "cancelled")
    assert ended.json()["endedAt"] is not None
    assert (again.status_code, again.json()["code"]) == (409, "subscription_not_cancellable")
    assert await admin.refund_rows() == []
    assert "billing.subscription.cancelled_by_admin" in await admin.audit_actions()
    row = await admin.subscription_row(started["subscriptionId"])
    assert row.status == "cancelled"
    assert await admin.wallet_balance(admin.primary_id) == SUBSCRIPTION_CREDITS


async def test_cancelling_needs_a_known_subscription_and_a_valid_body(admin: BillingApi) -> None:
    missing = await post(admin, f"/subscriptions/{UNKNOWN_ID}/cancel", {"immediately": True})
    invalid = await post(admin, f"/subscriptions/{UNKNOWN_ID}/cancel", {})
    extra = await post(admin, f"/subscriptions/{UNKNOWN_ID}/cancel", {"immediately": True, "refund": True})

    assert (missing.status_code, missing.json()["code"]) == (404, "subscription_not_found")
    assert invalid.status_code == extra.status_code == 422
