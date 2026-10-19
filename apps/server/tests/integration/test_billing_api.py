import asyncio
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text
from tests.integration.billing_support import PACK_CREDITS, PACK_PRICE, BillingApi, create_product
from tests.integration.test_auth import csrf

from motionile.core.errors import PROBLEM_MEDIA_TYPE
from motionile.modules.billing import invalidate_product_cache
from motionile.modules.billing.states import OrderStatus


async def test_a_credit_pack_purchase_runs_end_to_end_through_the_http_api(billing_api: BillingApi) -> None:
    created = await billing_api.create_order()

    assert created.status_code == 201, created.text
    checkout = created.json()
    assert created.headers["location"] == f"/v1/billing/orders/{checkout['orderId']}"
    assert set(checkout) == {
        "orderId",
        "keyId",
        "razorpayOrderId",
        "amountPaise",
        "currency",
        "name",
        "description",
        "customerId",
        "prefill",
    }
    assert (checkout["amountPaise"], checkout["currency"], checkout["name"]) == (PACK_PRICE, "INR", "Motionile")
    assert checkout["prefill"]["email"] == "billing-primary@example.com"
    assert checkout["keyId"].startswith("rzp_test_")
    pending = (await billing_api.primary.get(f"/v1/billing/orders/{checkout['orderId']}")).json()
    assert pending["status"] == "pending"
    assert pending["paidAt"] is None

    paid = await billing_api.pay(checkout["razorpayOrderId"])
    verified = await billing_api.verify(paid)

    assert verified.status_code == 200, verified.text
    assert verified.json() == {"orderId": checkout["orderId"], "status": "paid", "creditsGranted": PACK_CREDITS}
    order = (await billing_api.primary.get(f"/v1/billing/orders/{checkout['orderId']}")).json()
    assert order["status"] == "paid"
    assert order["paidAt"] is not None
    assert (order["kind"], order["productCode"], order["amountPaise"], order["creditsGranted"]) == (
        "credit_pack",
        billing_api.pack_code,
        PACK_PRICE,
        PACK_CREDITS,
    )
    wallet = (await billing_api.primary.get("/v1/credits/wallet")).json()
    assert (wallet["balance"], wallet["reserved"], wallet["available"]) == (PACK_CREDITS, 0, PACK_CREDITS)
    [payment] = await billing_api.payment_rows()
    assert (payment.status, payment.credits_granted, payment.amount_paise) == ("captured", PACK_CREDITS, PACK_PRICE)
    assert await billing_api.ledger_rows(billing_api.primary_id) == [
        ("purchase", PACK_CREDITS, f"payment:{payment.id}")
    ]
    async with billing_api.database.transaction() as session:
        lots = (
            await session.execute(
                text("SELECT source, amount, remaining, expires_at, ref_type, ref_id FROM credit_lots")
            )
        ).all()
    assert [tuple(lot) for lot in lots] == [("purchase", PACK_CREDITS, PACK_CREDITS, None, "payment", payment.id)]
    [receipt] = billing_api.recorded.receipts
    assert (receipt.user_id, receipt.amount_paise, receipt.credits) == (
        billing_api.primary_id,
        PACK_PRICE,
        PACK_CREDITS,
    )
    assert await billing_api.audit_actions() == ["billing.order.paid"]


async def test_verifying_again_with_a_new_key_or_the_same_key_grants_nothing_more(billing_api: BillingApi) -> None:
    checkout = await billing_api.checkout()
    paid = await billing_api.pay(checkout["razorpayOrderId"])
    key = billing_api.keys()
    first = await billing_api.verify(paid, key=key)

    replayed = await billing_api.verify(paid, key=key)
    fresh = await billing_api.verify(paid)

    assert replayed.headers["idempotent-replayed"] == "true"
    assert replayed.json() == first.json() == fresh.json()
    assert await billing_api.wallet_balance(billing_api.primary_id) == PACK_CREDITS
    assert len(await billing_api.ledger_rows(billing_api.primary_id)) == 1
    assert len(billing_api.recorded.receipts) == 1


async def test_verification_never_trusts_the_signature_alone(billing_api: BillingApi) -> None:
    checkout = await billing_api.checkout()
    unpaid = {
        "razorpay_order_id": checkout["razorpayOrderId"],
        "razorpay_payment_id": "pay_never_happened",
    }
    signature = billing_api.sign(unpaid["razorpay_order_id"], unpaid["razorpay_payment_id"])

    response = await billing_api.verify(unpaid, signature=signature)

    assert response.status_code == 502
    assert response.json()["code"] == "payment_provider_error"
    assert await billing_api.wallet_balance(billing_api.primary_id) == 0
    assert (await billing_api.order_row(checkout["orderId"])).status == "pending"


async def test_a_tampered_signature_is_a_400_problem(billing_api: BillingApi) -> None:
    checkout = await billing_api.checkout()
    paid = await billing_api.pay(checkout["razorpayOrderId"])

    response = await billing_api.verify(paid, signature="0" * 64)

    assert response.status_code == 400
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.json()["code"] == "invalid_payment_signature"
    assert response.json()["type"] == "urn:motionile:problem:invalid_payment_signature"
    assert await billing_api.wallet_balance(billing_api.primary_id) == 0


async def test_an_authorized_payment_waits_for_capture(billing_api: BillingApi) -> None:
    checkout = await billing_api.checkout()
    paid = await billing_api.pay(checkout["razorpayOrderId"], outcome="authorized")
    paid["razorpay_signature"] = billing_api.sign(paid["razorpay_order_id"], paid["razorpay_payment_id"])

    response = await billing_api.verify(paid)

    assert response.json() == {"orderId": checkout["orderId"], "status": "pending", "creditsGranted": 0}
    assert await billing_api.wallet_balance(billing_api.primary_id) == 0
    [payment] = await billing_api.payment_rows()
    assert payment.status == "authorized"


async def test_verify_requires_an_idempotency_key_and_csrf(billing_api: BillingApi) -> None:
    checkout = await billing_api.checkout()
    paid = await billing_api.pay(checkout["razorpayOrderId"])
    body = {
        "razorpayOrderId": paid["razorpay_order_id"],
        "razorpayPaymentId": paid["razorpay_payment_id"],
        "razorpaySignature": paid["razorpay_signature"],
    }

    no_key = await billing_api.primary.post("/v1/billing/payments/verify", json=body, headers=csrf(billing_api.primary))
    no_csrf = await billing_api.primary.post(
        "/v1/billing/payments/verify", json=body, headers={"Idempotency-Key": billing_api.keys()}
    )
    anonymous = await billing_api.anonymous.post(
        "/v1/billing/payments/verify", json=body, headers={"Idempotency-Key": billing_api.keys()}
    )

    assert (no_key.status_code, no_key.json()["code"]) == (400, "idempotency_key_required")
    assert no_csrf.status_code in {401, 403}
    assert anonymous.status_code in {401, 403}
    assert await billing_api.wallet_balance(billing_api.primary_id) == 0


async def test_replaying_order_creation_returns_the_same_order_and_checkout(billing_api: BillingApi) -> None:
    key = billing_api.keys()
    first = await billing_api.create_order(key=key)

    replay = await billing_api.create_order(key=key)

    assert replay.status_code == 201
    assert replay.headers["idempotent-replayed"] == "true"
    assert replay.json() == first.json()
    assert replay.headers["location"] == first.headers["location"]
    assert await billing_api.remote_order_count() == 1


async def test_the_same_key_with_another_body_is_a_conflict(billing_api: BillingApi) -> None:
    other_pack = f"{billing_api.pack_code}_x"
    await create_product(billing_api.database, other_pack)
    key = billing_api.keys()
    await billing_api.create_order(key=key)

    response = await billing_api.create_order(key=key, body={"productCode": other_pack})

    assert response.status_code == 409
    assert response.json()["code"] == "idempotency_key_reused"


async def test_order_creation_requires_an_idempotency_key(billing_api: BillingApi) -> None:
    response = await billing_api.primary.post(
        "/v1/billing/orders", json={"productCode": billing_api.pack_code}, headers=csrf(billing_api.primary)
    )

    assert (response.status_code, response.json()["code"]) == (400, "idempotency_key_required")


async def test_order_creation_requires_authentication(billing_api: BillingApi) -> None:
    response = await billing_api.anonymous.post(
        "/v1/billing/orders", json={"productCode": billing_api.pack_code}, headers={"Idempotency-Key": "k"}
    )

    assert response.status_code in {401, 403}
    assert await billing_api.remote_order_count() == 0


@pytest.mark.parametrize(
    "extra",
    [
        {"amountPaise": 1},
        {"amount": 1},
        {"currency": "USD"},
        {"creditsGranted": 1_000_000},
        {"credits": 1_000_000},
        {"userId": "00000000-0000-0000-0000-000000000000"},
        {"price": 1},
        {"razorpayOrderId": "order_x"},
    ],
)
async def test_client_supplied_money_fields_are_rejected(billing_api: BillingApi, extra: dict[str, Any]) -> None:
    response = await billing_api.create_order(body={"productCode": billing_api.pack_code, **extra})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"
    assert await billing_api.remote_order_count() == 0
    async with billing_api.database.transaction() as session:
        assert (await session.scalar(text("SELECT count(*) FROM orders"))) == 0


@pytest.mark.parametrize("body", [{}, {"productCode": ""}, {"productCode": "Bad Code!"}, {"productCode": "x" * 61}])
async def test_the_product_code_is_validated(billing_api: BillingApi, body: dict[str, Any]) -> None:
    response = await billing_api.create_order(body=body)

    assert response.status_code == 422


async def test_unknown_inactive_and_subscription_products_cannot_be_ordered(billing_api: BillingApi) -> None:
    await create_product(billing_api.database, "pack_retired", active=False)
    await create_product(billing_api.database, "pro_monthly", kind="subscription")

    unknown = await billing_api.create_order(body={"productCode": "pack_missing"})
    retired = await billing_api.create_order(body={"productCode": "pack_retired"})
    subscription = await billing_api.create_order(body={"productCode": "pro_monthly"})

    assert (unknown.status_code, unknown.json()["code"]) == (404, "product_not_found")
    assert (retired.status_code, retired.json()["code"]) == (404, "product_not_found")
    assert (subscription.status_code, subscription.json()["code"]) == (422, "product_not_purchasable")
    assert await billing_api.remote_order_count() == 0


async def test_a_timeout_after_the_provider_created_the_order_is_recovered_without_a_second_order(
    billing_api: BillingApi,
) -> None:
    armed = await billing_api.primary.post(
        "/v1/_test/razorpay/faults", json={"operation": "create_order", "kind": "timeout_after_create"}
    )
    assert armed.status_code == 200

    response = await billing_api.create_order()

    assert response.status_code == 201, response.text
    assert await billing_api.remote_order_count() == 1
    order = await billing_api.order_row(response.json()["orderId"])
    assert (order.status, order.razorpay_order_id) == ("pending", response.json()["razorpayOrderId"])


async def test_a_timeout_before_creation_leaves_the_order_created_and_the_same_key_completes_it(
    billing_api: BillingApi,
) -> None:
    await billing_api.primary.post(
        "/v1/_test/razorpay/faults", json={"operation": "create_order", "kind": "timeout_before_create"}
    )
    key = billing_api.keys()

    failed = await billing_api.create_order(key=key)

    assert failed.status_code == 503
    assert failed.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert failed.json()["code"] == "payment_provider_unavailable"
    assert failed.headers["retry-after"]
    async with billing_api.database.transaction() as session:
        rows = (await session.execute(text("SELECT id, status, razorpay_order_id FROM orders"))).all()
    assert [(row[1], row[2]) for row in rows] == [("created", None)]
    assert await billing_api.remote_order_count() == 0

    retried = await billing_api.create_order(key=key)

    assert retried.status_code == 201, retried.text
    assert retried.json()["orderId"] == str(rows[0][0])
    assert await billing_api.remote_order_count() == 1
    assert (await billing_api.order_row(rows[0][0])).status == "pending"


async def test_someone_elses_order_is_invisible_everywhere(billing_api: BillingApi) -> None:
    checkout = await billing_api.checkout()
    paid = await billing_api.pay(checkout["razorpayOrderId"])
    await billing_api.verify(paid)

    status = await billing_api.other.get(f"/v1/billing/orders/{checkout['orderId']}")
    stolen = await billing_api.verify(paid, billing_api.other)
    history = await billing_api.other.get("/v1/billing/history")

    assert (status.status_code, status.json()["code"]) == (404, "order_not_found")
    assert (stolen.status_code, stolen.json()["code"]) == (404, "order_not_found")
    assert history.json() == {"items": [], "nextCursor": None}
    assert await billing_api.wallet_balance(billing_api.other_id) == 0


async def test_another_user_cannot_settle_my_unpaid_order_by_verifying_it(billing_api: BillingApi) -> None:
    checkout = await billing_api.checkout()
    paid = await billing_api.pay(checkout["razorpayOrderId"])

    stolen = await billing_api.verify(paid, billing_api.other)

    assert stolen.status_code == 404
    assert (await billing_api.order_row(checkout["orderId"])).status == "pending"
    assert await billing_api.wallet_balance(billing_api.primary_id) == 0
    assert await billing_api.wallet_balance(billing_api.other_id) == 0


async def test_orders_and_history_require_authentication(billing_api: BillingApi) -> None:
    checkout = await billing_api.checkout()

    order = await billing_api.anonymous.get(f"/v1/billing/orders/{checkout['orderId']}")
    history = await billing_api.anonymous.get("/v1/billing/history")

    assert order.status_code == 401
    assert history.status_code == 401


async def test_a_malformed_order_id_is_a_validation_problem(billing_api: BillingApi) -> None:
    response = await billing_api.primary.get("/v1/billing/orders/not-a-uuid")

    assert response.status_code == 422


async def test_history_lists_orders_and_payments_newest_first_with_cursors(billing_api: BillingApi) -> None:
    checkout = await billing_api.checkout()
    paid = await billing_api.pay(checkout["razorpayOrderId"])
    await billing_api.verify(paid)
    [payment] = await billing_api.payment_rows()

    history = (await billing_api.primary.get("/v1/billing/history")).json()

    assert [(item["type"], item["id"]) for item in history["items"]] == [
        ("payment", str(payment.id)),
        ("order", checkout["orderId"]),
    ]
    payment_item, order_item = history["items"]
    assert (payment_item["title"], payment_item["creditsGranted"], payment_item["orderId"]) == (
        f"Payment for {billing_api.pack_code.replace('_', ' ').title()}",
        PACK_CREDITS,
        checkout["orderId"],
    )
    assert (order_item["status"], order_item["amountPaise"], order_item["currency"]) == ("paid", PACK_PRICE, "INR")
    first_page = (await billing_api.primary.get("/v1/billing/history", params={"limit": 1})).json()
    assert [item["type"] for item in first_page["items"]] == ["payment"]
    assert first_page["nextCursor"]
    second_page = (
        await billing_api.primary.get("/v1/billing/history", params={"limit": 1, "cursor": first_page["nextCursor"]})
    ).json()
    assert [item["type"] for item in second_page["items"]] == ["order"]
    assert second_page["nextCursor"] is None


async def test_history_rejects_forged_cursors(billing_api: BillingApi) -> None:
    response = await billing_api.primary.get("/v1/billing/history", params={"cursor": "forged.cursor"})

    assert response.status_code == 422


async def test_a_mismatched_amount_is_recorded_without_credits_and_raises_an_alert(billing_api: BillingApi) -> None:
    checkout = await billing_api.checkout()
    paid = await billing_api.pay(checkout["razorpayOrderId"], amountPaise=PACK_PRICE - 1000)

    response = await billing_api.verify(paid)

    assert response.json() == {"orderId": checkout["orderId"], "status": "pending", "creditsGranted": 0}
    order = await billing_api.order_row(checkout["orderId"])
    assert (order.status, order.flag_reason) == ("pending", "amount_mismatch")
    assert order.flagged_at is not None
    [payment] = await billing_api.payment_rows()
    assert (payment.amount_paise, payment.credits_granted) == (PACK_PRICE - 1000, 0)
    assert await billing_api.wallet_balance(billing_api.primary_id) == 0
    assert [code for code, _ in billing_api.recorded.alerts] == ["billing.payment_mismatch"]
    assert billing_api.recorded.receipts == []
    assert await billing_api.audit_actions() == ["billing.payment.flagged"]


async def test_products_are_public_cached_and_revalidated_with_etags(billing_api: BillingApi) -> None:
    await create_product(billing_api.database, "pack_hidden", active=False)
    await create_product(billing_api.database, "pro_monthly", kind="subscription", price=49_900, credit_amount=300)

    first = await billing_api.anonymous.get("/v1/billing/products")

    assert first.status_code == 200
    assert first.headers["cache-control"] == "public, max-age=60, s-maxage=300, stale-while-revalidate=600"
    etag = first.headers["etag"]
    assert etag.startswith('"')
    assert not etag.startswith("W/")
    body = first.json()
    assert [item["code"] for item in body["creditPacks"]] == [billing_api.pack_code]
    assert [item["code"] for item in body["subscriptions"]] == ["pro_monthly"]
    pack = body["creditPacks"][0]
    assert set(pack) == {
        "code",
        "name",
        "description",
        "pricePaise",
        "currency",
        "interval",
        "planKey",
        "creditsGranted",
        "features",
        "sortOrder",
    }
    assert (pack["pricePaise"], pack["creditsGranted"], pack["interval"], pack["features"]) == (
        PACK_PRICE,
        PACK_CREDITS,
        None,
        ["100 credits"],
    )
    assert (body["subscriptions"][0]["interval"], body["subscriptions"][0]["planKey"]) == ("month", "pro_monthly_plan")

    conditional = await billing_api.anonymous.get("/v1/billing/products", headers={"If-None-Match": etag})
    stale = await billing_api.anonymous.get("/v1/billing/products", headers={"If-None-Match": '"other"'})

    assert conditional.status_code == 304
    assert conditional.content == b""
    assert conditional.headers["etag"] == etag
    assert conditional.headers["cache-control"] == first.headers["cache-control"]
    assert (stale.status_code, stale.headers["etag"]) == (200, etag)


async def test_the_product_cache_serves_until_it_is_invalidated(billing_api: BillingApi) -> None:
    first = await billing_api.anonymous.get("/v1/billing/products")
    await create_product(billing_api.database, "pack_new", sort_order=5)

    cached = await billing_api.anonymous.get("/v1/billing/products")
    assert cached.headers["etag"] == first.headers["etag"]
    assert len(cached.json()["creditPacks"]) == 1

    await invalidate_product_cache(billing_api.resources.redis_store)
    refreshed = await billing_api.anonymous.get("/v1/billing/products")

    assert [item["code"] for item in refreshed.json()["creditPacks"]] == [billing_api.pack_code, "pack_new"]
    assert refreshed.headers["etag"] != first.headers["etag"]


async def test_the_product_listing_needs_no_authentication_or_csrf(billing_api: BillingApi) -> None:
    response = await billing_api.anonymous.get("/v1/billing/products")

    assert response.status_code == 200
    assert "set-cookie" not in response.headers


async def test_the_database_time_of_expiry_follows_the_order_expiry_setting(billing_api: BillingApi) -> None:
    checkout = await billing_api.checkout()

    order = await billing_api.order_row(checkout["orderId"])

    assert order.expires_at == billing_api.clock.now() + timedelta(
        seconds=billing_api.resources.settings.billing.order_expiry_seconds
    )
    assert order.status == OrderStatus.PENDING.value


async def test_concurrent_identical_requests_create_one_order(billing_api: BillingApi) -> None:
    key = billing_api.keys()

    responses = await asyncio.gather(*(billing_api.create_order(key=key) for _ in range(4)))

    statuses = sorted(response.status_code for response in responses)
    assert statuses.count(201) >= 1
    assert set(statuses) <= {201, 409}
    assert await billing_api.remote_order_count() == 1
    async with billing_api.database.transaction() as session:
        assert (await session.scalar(text("SELECT count(*) FROM orders"))) == 1


@pytest.mark.slow
async def test_two_concurrent_first_purchases_end_with_one_customer(billing_api: BillingApi) -> None:
    profiles = await asyncio.gather(*(billing_api.services.customers.ensure(billing_api.primary_id) for _ in range(6)))

    assert len({profile.razorpay_customer_id for profile in profiles}) == 1
    async with billing_api.database.transaction() as session:
        rows = (await session.execute(text("SELECT user_id, razorpay_customer_id FROM billing_customers"))).all()
    assert [(row[0], row[1]) for row in rows] == [(billing_api.primary_id, profiles[0].razorpay_customer_id)]


async def test_a_second_purchase_reuses_the_customer(billing_api: BillingApi) -> None:
    first = await billing_api.checkout()
    second = await billing_api.checkout()

    assert first["customerId"] == second["customerId"]
    async with billing_api.database.transaction() as session:
        assert (await session.scalar(text("SELECT count(*) FROM billing_customers"))) == 1
