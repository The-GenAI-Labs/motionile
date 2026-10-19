from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from tests.integration.billing_support import SUBSCRIPTION_CREDITS, SUBSCRIPTION_PRICE, BillingApi

from motionile.core.errors import PROBLEM_MEDIA_TYPE


async def remote_subscription_count(api: BillingApi) -> int:
    key = api.resources.redis_store.keys.key("fake_razorpay", "sequence", "sub")
    raw = await api.resources.redis_store.get(key)
    return int(raw) if raw is not None else 0


def event_statuses(events: list[Any]) -> list[tuple[str, str, str | None]]:
    return [(event.event_type, event.status, event.ignored_reason) for event in events]


async def test_a_subscription_runs_from_checkout_to_credits_receipt_and_paid_order(billing_api: BillingApi) -> None:
    code = await billing_api.plan_product()

    created = await billing_api.subscribe(code)

    assert created.status_code == 201, created.text
    checkout = created.json()
    assert set(checkout) == {
        "orderId",
        "subscriptionId",
        "keyId",
        "razorpaySubscriptionId",
        "name",
        "description",
        "customerId",
        "prefill",
    }
    assert checkout["name"] == "Motionile"
    assert checkout["keyId"].startswith("rzp_test_")
    assert checkout["prefill"]["email"] == "billing-primary@example.com"
    assert "amountPaise" not in checkout
    assert (await billing_api.get_subscription())["subscription"] is None
    order = (await billing_api.primary.get(f"/v1/billing/orders/{checkout['orderId']}")).json()
    assert (order["status"], order["kind"], order["amountPaise"]) == ("pending", "subscription", SUBSCRIPTION_PRICE)

    authorized = await billing_api.authorize_subscription(checkout["razorpaySubscriptionId"])
    verified = await billing_api.verify_subscription(authorized)

    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "authenticated"
    assert await billing_api.wallet_balance(billing_api.primary_id) == 0
    assert (await billing_api.get_subscription())["subscription"]["status"] == "authenticated"

    await billing_api.transition(checkout["razorpaySubscriptionId"], "activated")
    await billing_api.deliver(
        event="subscription.charged",
        subscriptionId=checkout["razorpaySubscriptionId"],
        paymentId=authorized["razorpay_payment_id"],
    )
    await billing_api.process_dispatched()

    current = (await billing_api.get_subscription())["subscription"]
    assert set(current) == {
        "id",
        "status",
        "product",
        "pendingProduct",
        "currentPeriodStart",
        "currentPeriodEnd",
        "nextChargeAt",
        "cancelAtPeriodEnd",
        "cancelledAt",
        "endsAt",
    }
    assert current["id"] == checkout["subscriptionId"]
    assert current["status"] == "active"
    assert current["product"] == {
        "code": code,
        "name": code.replace("_", " ").title(),
        "interval": "month",
        "pricePaise": SUBSCRIPTION_PRICE,
        "creditsGranted": SUBSCRIPTION_CREDITS,
        "planKey": f"{code}_plan",
    }
    assert (current["pendingProduct"], current["cancelAtPeriodEnd"], current["endsAt"]) == (None, False, None)
    assert current["nextChargeAt"] == current["currentPeriodEnd"]
    assert await billing_api.wallet_balance(billing_api.primary_id) == SUBSCRIPTION_CREDITS
    [lot] = await billing_api.lot_rows()
    source, amount, remaining, expires_at = lot
    assert (source, amount, remaining) == ("subscription", SUBSCRIPTION_CREDITS, SUBSCRIPTION_CREDITS)
    assert expires_at is not None
    assert expires_at == datetime.fromisoformat(current["currentPeriodEnd"])
    [payment] = await billing_api.payment_rows()
    assert (str(payment.subscription_id), str(payment.order_id)) == (checkout["subscriptionId"], checkout["orderId"])
    assert (payment.credits_granted, payment.status) == (SUBSCRIPTION_CREDITS, "captured")
    assert await billing_api.ledger_rows(billing_api.primary_id) == [
        ("subscription_grant", SUBSCRIPTION_CREDITS, f"payment:{payment.id}")
    ]
    order = (await billing_api.primary.get(f"/v1/billing/orders/{checkout['orderId']}")).json()
    assert order["status"] == "paid"
    assert billing_api.recorded.notice_templates() == ["subscription_activated"]
    context = billing_api.recorded.notices[0].context
    assert context["credits"] == str(SUBSCRIPTION_CREDITS)
    assert context["amount"].endswith("incl. GST")
    assert [(event.event_type, event.status) for event in await billing_api.event_rows()] == [
        ("subscription.activated", "processed"),
        ("subscription.charged", "processed"),
    ]


async def test_a_renewal_charged_twice_grants_credits_once(billing_api: BillingApi) -> None:
    code = await billing_api.plan_product()
    started = await billing_api.activate_subscription(code)
    remote_id = started["razorpaySubscriptionId"]
    moved = await billing_api.transition(remote_id, "charged", eventId="evt_renewal", repeat=3)
    payment_id = moved["razorpayPaymentId"]

    await billing_api.deliver(event="subscription.charged", subscriptionId=remote_id, paymentId=payment_id)
    await billing_api.deliver(
        event="subscription.charged", subscriptionId=remote_id, paymentId=payment_id, eventId="evt_renewal"
    )
    processed = await billing_api.process_dispatched()

    assert len(processed) == 2
    assert await billing_api.wallet_balance(billing_api.primary_id) == 2 * SUBSCRIPTION_CREDITS
    assert len(await billing_api.lot_rows()) == 2
    assert len(await billing_api.payment_rows()) == 2
    assert len(await billing_api.ledger_rows(billing_api.primary_id)) == 2
    row = await billing_api.subscription_row(started["subscriptionId"])
    assert (row.status, row.paid_count) == ("active", 2)
    assert billing_api.recorded.notice_templates() == ["subscription_activated", "renewal_receipt"]
    assert all(event.status == "processed" for event in await billing_api.event_rows())


async def test_a_charge_that_arrives_before_the_activation_activates_the_subscription(billing_api: BillingApi) -> None:
    code = await billing_api.plan_product()
    started = await billing_api.started_subscription(code)
    remote_id = started["razorpaySubscriptionId"]
    authorized = await billing_api.authorize_subscription(remote_id)
    await billing_api.transition(remote_id, "activated", emit=False)

    await billing_api.deliver(
        event="subscription.charged", subscriptionId=remote_id, paymentId=authorized["razorpay_payment_id"]
    )
    await billing_api.process_dispatched()

    assert (await billing_api.subscription_row(started["subscriptionId"])).status == "active"
    assert await billing_api.wallet_balance(billing_api.primary_id) == SUBSCRIPTION_CREDITS
    await billing_api.deliver(event="subscription.activated", subscriptionId=remote_id)
    await billing_api.process_dispatched()
    assert (await billing_api.subscription_row(started["subscriptionId"])).status == "active"
    assert await billing_api.wallet_balance(billing_api.primary_id) == SUBSCRIPTION_CREDITS
    assert event_statuses(await billing_api.event_rows()) == [
        ("subscription.charged", "processed", None),
        ("subscription.activated", "processed", None),
    ]


async def test_a_stale_event_is_ignored_and_a_stale_charge_is_still_credited(billing_api: BillingApi) -> None:
    code = await billing_api.plan_product()
    started = await billing_api.activate_subscription(code)
    remote_id = started["razorpaySubscriptionId"]
    moved = await billing_api.transition(remote_id, "charged", emit=False)
    old = int((billing_api.clock.now() - timedelta(days=1)).timestamp())
    await billing_api.transition(remote_id, "paused", emit=True)
    await billing_api.process_dispatched()
    before = await billing_api.subscription_row(started["subscriptionId"])

    await billing_api.deliver(event="subscription.pending", subscriptionId=remote_id, createdAt=old)
    await billing_api.deliver(
        event="subscription.charged", subscriptionId=remote_id, paymentId=moved["razorpayPaymentId"], createdAt=old
    )
    await billing_api.process_dispatched()

    after = await billing_api.subscription_row(started["subscriptionId"])
    assert after.status == before.status == "paused"
    assert after.last_event_at == before.last_event_at
    events = event_statuses(await billing_api.event_rows())
    assert events[-2:] == [("subscription.pending", "ignored", "stale"), ("subscription.charged", "ignored", "stale")]
    assert await billing_api.wallet_balance(billing_api.primary_id) == 2 * SUBSCRIPTION_CREDITS


async def test_a_plan_change_takes_effect_with_the_next_renewal(billing_api: BillingApi) -> None:
    small = await billing_api.plan_product()
    large = await billing_api.plan_product(price=199_900, credit_amount=1_500)
    started = await billing_api.activate_subscription(small)
    remote_id = started["razorpaySubscriptionId"]

    changed = await billing_api.primary.post(
        "/v1/billing/subscription/change", json={"productCode": large}, headers=billing_api.headers(billing_api.primary)
    )

    assert changed.status_code == 200, changed.text
    assert changed.json()["product"]["code"] == small
    assert changed.json()["pendingProduct"]["code"] == large
    assert (await billing_api.get_subscription())["subscription"]["pendingProduct"]["pricePaise"] == 199_900
    assert await billing_api.audit_actions("billing.subscription.change") == ["billing.subscription.change_scheduled"]

    await billing_api.renew(remote_id)

    current = (await billing_api.get_subscription())["subscription"]
    assert current["product"]["code"] == large
    assert current["pendingProduct"] is None
    assert await billing_api.wallet_balance(billing_api.primary_id) == SUBSCRIPTION_CREDITS + 1_500
    assert sorted(amount for _, amount, _, _ in await billing_api.lot_rows()) == [SUBSCRIPTION_CREDITS, 1_500]


async def test_changing_plans_needs_an_active_subscription_and_a_different_plan(billing_api: BillingApi) -> None:
    small = await billing_api.plan_product()
    other = await billing_api.plan_product(price=199_900, credit_amount=1_500)
    headers = billing_api.headers(billing_api.primary)

    nothing = await billing_api.primary.post(
        "/v1/billing/subscription/change", json={"productCode": other}, headers=headers
    )
    await billing_api.activate_subscription(small)
    same = await billing_api.primary.post(
        "/v1/billing/subscription/change", json={"productCode": small}, headers=headers
    )
    pack = await billing_api.primary.post(
        "/v1/billing/subscription/change", json={"productCode": billing_api.pack_code}, headers=headers
    )
    missing = await billing_api.primary.post(
        "/v1/billing/subscription/change", json={"productCode": "no_such_plan"}, headers=headers
    )
    extra = await billing_api.primary.post(
        "/v1/billing/subscription/change", json={"productCode": other, "amountPaise": 1}, headers=headers
    )

    assert (nothing.status_code, nothing.json()["code"]) == (404, "subscription_not_found")
    assert (same.status_code, same.json()["code"]) == (409, "subscription_not_changeable")
    assert (pack.status_code, pack.json()["code"]) == (422, "product_not_purchasable")
    assert (missing.status_code, missing.json()["code"]) == (404, "product_not_found")
    assert extra.status_code == 422
    assert same.headers["content-type"] == PROBLEM_MEDIA_TYPE


async def test_cancelling_keeps_access_until_the_period_ends_and_then_the_finalizer_closes_it(
    billing_api: BillingApi,
) -> None:
    code = await billing_api.plan_product()
    started = await billing_api.activate_subscription(code)
    remote_id = started["razorpaySubscriptionId"]

    cancelled = await billing_api.primary.post(
        "/v1/billing/subscription/cancel", headers=billing_api.headers(billing_api.primary)
    )
    again = await billing_api.primary.post(
        "/v1/billing/subscription/cancel", headers=billing_api.headers(billing_api.primary)
    )

    assert cancelled.status_code == again.status_code == 200
    body = cancelled.json()
    assert (body["status"], body["cancelAtPeriodEnd"]) == ("active", True)
    assert body["cancelledAt"] is not None
    assert body["endsAt"] == body["currentPeriodEnd"]
    assert billing_api.recorded.notice_templates() == ["subscription_activated", "cancellation_scheduled"]
    assert await billing_api.audit_actions("billing.subscription.cancel") == ["billing.subscription.cancel_requested"]
    assert (await billing_api.get_subscription())["subscription"]["status"] == "active"
    early = await billing_api.services.subscriptions.finalizer.finalize()
    assert early.cancelled == 0

    await billing_api.end_period(started["subscriptionId"])
    late = await billing_api.services.subscriptions.finalizer.finalize()

    assert late.cancelled == 1
    row = await billing_api.subscription_row(started["subscriptionId"])
    assert (row.status, row.cancel_at_period_end) == ("cancelled", True)
    assert row.ended_at is not None
    assert (await billing_api.get_subscription())["subscription"] is None
    assert billing_api.recorded.notice_templates()[-1] == "subscription_ended"
    assert await billing_api.wallet_balance(billing_api.primary_id) == SUBSCRIPTION_CREDITS
    assert remote_id


async def test_an_authenticated_subscription_is_cancelled_at_once(billing_api: BillingApi) -> None:
    code = await billing_api.plan_product()
    started = await billing_api.started_subscription(code)
    authorized = await billing_api.authorize_subscription(started["razorpaySubscriptionId"])
    await billing_api.verify_subscription(authorized)

    cancelled = await billing_api.primary.post(
        "/v1/billing/subscription/cancel", headers=billing_api.headers(billing_api.primary)
    )

    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert (await billing_api.get_subscription())["subscription"] is None
    assert billing_api.recorded.notice_templates() == ["subscription_ended"]


async def test_failed_renewals_move_to_halted_and_grant_nothing(billing_api: BillingApi) -> None:
    code = await billing_api.plan_product()
    started = await billing_api.activate_subscription(code)
    remote_id = started["razorpaySubscriptionId"]

    await billing_api.transition(remote_id, "pending")
    await billing_api.process_dispatched()
    assert (await billing_api.get_subscription())["subscription"]["status"] == "pending"
    await billing_api.transition(remote_id, "halted")
    await billing_api.process_dispatched()

    assert (await billing_api.get_subscription())["subscription"]["status"] == "halted"
    assert await billing_api.wallet_balance(billing_api.primary_id) == SUBSCRIPTION_CREDITS
    assert len(await billing_api.lot_rows()) == 1
    assert billing_api.recorded.notice_templates()[-2:] == ["charge_failed", "subscription_halted"]
    blocked = await billing_api.subscribe(code)
    assert (blocked.status_code, blocked.json()["code"]) == (409, "subscription_exists")


async def test_a_second_live_subscription_is_refused_until_the_first_ends(billing_api: BillingApi) -> None:
    code = await billing_api.plan_product()
    await billing_api.activate_subscription(code)

    refused = await billing_api.subscribe(code)

    assert refused.status_code == 409
    assert refused.json()["code"] == "subscription_exists"
    assert refused.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert len(await billing_api.subscription_rows()) == 1
    await billing_api.primary.post("/v1/billing/subscription/cancel", headers=billing_api.headers(billing_api.primary))
    [first] = await billing_api.subscription_rows()
    await billing_api.end_period(first.id)
    await billing_api.services.subscriptions.finalizer.finalize()

    allowed = await billing_api.subscribe(code)

    assert allowed.status_code == 201, allowed.text
    assert len(await billing_api.subscription_rows()) == 2


async def test_one_users_subscription_cannot_be_verified_cancelled_or_changed_by_another(
    billing_api: BillingApi,
) -> None:
    code = await billing_api.plan_product()
    other_code = await billing_api.plan_product(price=199_900, credit_amount=1_500)
    started = await billing_api.started_subscription(code)
    authorized = await billing_api.authorize_subscription(started["razorpaySubscriptionId"])

    verify = await billing_api.verify_subscription(authorized, billing_api.other)
    assert (verify.status_code, verify.json()["code"]) == (404, "subscription_not_found")
    assert (await billing_api.subscription_row(started["subscriptionId"])).status == "created"
    await billing_api.verify_subscription(authorized)
    await billing_api.transition(started["razorpaySubscriptionId"], "activated")
    await billing_api.deliver(
        event="subscription.charged",
        subscriptionId=started["razorpaySubscriptionId"],
        paymentId=authorized["razorpay_payment_id"],
    )
    await billing_api.process_dispatched()

    cancel = await billing_api.other.post(
        "/v1/billing/subscription/cancel", headers=billing_api.headers(billing_api.other)
    )
    change = await billing_api.other.post(
        "/v1/billing/subscription/change",
        json={"productCode": other_code},
        headers=billing_api.headers(billing_api.other),
    )
    current = await billing_api.get_subscription(billing_api.other)

    assert (cancel.status_code, cancel.json()["code"]) == (404, "subscription_not_found")
    assert (change.status_code, change.json()["code"]) == (404, "subscription_not_found")
    assert current == {"subscription": None}
    row = await billing_api.subscription_row(started["subscriptionId"])
    assert (row.status, row.cancel_at_period_end, row.pending_product_id) == ("active", False, None)


async def test_verification_rejects_a_bad_signature_and_an_unknown_subscription(billing_api: BillingApi) -> None:
    code = await billing_api.plan_product()
    started = await billing_api.started_subscription(code)
    authorized = await billing_api.authorize_subscription(started["razorpaySubscriptionId"])

    tampered = await billing_api.verify_subscription(authorized, signature="0" * 64)
    unknown = await billing_api.verify_subscription({**authorized, "razorpay_subscription_id": "sub_unknown"})

    assert (tampered.status_code, tampered.json()["code"]) == (400, "invalid_payment_signature")
    assert unknown.status_code in {400, 404}
    assert (await billing_api.subscription_row(started["subscriptionId"])).status == "created"


async def test_creating_and_verifying_need_an_idempotency_key_and_replay_safely(billing_api: BillingApi) -> None:
    code = await billing_api.plan_product()
    missing = await billing_api.primary.post(
        "/v1/billing/subscriptions", json={"productCode": code}, headers=csrf_only(billing_api)
    )
    key = billing_api.keys()

    first = await billing_api.subscribe(code, key=key)
    replayed = await billing_api.subscribe(code, key=key)
    reused = await billing_api.subscribe(billing_api.pack_code, key=key)

    assert (missing.status_code, missing.json()["code"]) == (400, "idempotency_key_required")
    assert first.status_code == 201
    assert replayed.headers["idempotent-replayed"] == "true"
    assert replayed.json() == first.json()
    assert reused.status_code == 409
    assert await remote_subscription_count(billing_api) == 1
    authorized = await billing_api.authorize_subscription(first.json()["razorpaySubscriptionId"])
    no_key = await billing_api.primary.post(
        "/v1/billing/subscriptions/verify",
        json={
            "razorpayPaymentId": authorized["razorpay_payment_id"],
            "razorpaySubscriptionId": authorized["razorpay_subscription_id"],
            "razorpaySignature": authorized["razorpay_signature"],
        },
        headers=csrf_only(billing_api),
    )
    assert (no_key.status_code, no_key.json()["code"]) == (400, "idempotency_key_required")


def csrf_only(api: BillingApi) -> dict[str, str]:
    return {key: value for key, value in api.headers(api.primary).items() if key.lower() != "idempotency-key"}


async def test_only_subscription_plans_can_be_started_and_requests_are_strict(billing_api: BillingApi) -> None:
    code = await billing_api.plan_product()
    pack = await billing_api.subscribe(billing_api.pack_code)
    missing = await billing_api.subscribe("no_such_plan")
    extra = await billing_api.subscribe("x", body={"productCode": "x", "amountPaise": 1})
    bad_code = await billing_api.subscribe("x", body={"productCode": "Not A Code"})
    anonymous = await billing_api.anonymous.post(
        "/v1/billing/subscriptions", json={"productCode": code}, headers={"Idempotency-Key": billing_api.keys()}
    )

    assert (pack.status_code, pack.json()["code"]) == (422, "product_not_purchasable")
    assert (missing.status_code, missing.json()["code"]) == (404, "product_not_found")
    assert extra.status_code == bad_code.status_code == 422
    assert anonymous.status_code in {401, 403}
    assert await billing_api.subscription_rows() == []


async def test_a_provider_timeout_after_creation_is_recovered_without_a_second_subscription(
    billing_api: BillingApi,
) -> None:
    code = await billing_api.plan_product()
    await billing_api.arm_fault("create_subscription", "timeout_after_create")

    created = await billing_api.subscribe(code)

    assert created.status_code == 201, created.text
    assert await remote_subscription_count(billing_api) == 1
    [row] = await billing_api.subscription_rows()
    assert row.razorpay_subscription_id == created.json()["razorpaySubscriptionId"]


async def test_a_provider_outage_leaves_a_retryable_checkout(billing_api: BillingApi) -> None:
    code = await billing_api.plan_product()
    key = billing_api.keys()
    await billing_api.arm_fault("create_subscription", "timeout_before_create")

    failed = await billing_api.subscribe(code, key=key)
    retried = await billing_api.subscribe(code, key=key)

    assert failed.status_code == 503
    assert failed.json()["code"] == "payment_provider_unavailable"
    assert failed.headers["retry-after"]
    assert retried.status_code == 201, retried.text
    assert await remote_subscription_count(billing_api) == 1
    assert len(await billing_api.subscription_rows()) == 1


async def test_subscription_credits_do_not_expire_when_rollover_is_enabled(billing_api: BillingApi) -> None:
    code = await billing_api.plan_product()
    async with billing_api.database.transaction() as session:
        await session.execute(
            text(
                "INSERT INTO system_settings (key, value, version) "
                "VALUES ('billing.subscription_rollover', 'true'::jsonb, 1)"
            )
        )
    try:
        await billing_api.activate_subscription(code)
    finally:
        async with billing_api.database.transaction() as session:
            await session.execute(text("DELETE FROM system_settings WHERE key = 'billing.subscription_rollover'"))

    [(source, _, _, expires_at)] = await billing_api.lot_rows()
    assert (source, expires_at) == ("subscription", None)


async def test_the_daily_sync_repairs_a_subscription_whose_webhooks_were_dropped(billing_api: BillingApi) -> None:
    code = await billing_api.plan_product()
    started = await billing_api.started_subscription(code)
    remote_id = started["razorpaySubscriptionId"]
    authorized = await billing_api.authorize_subscription(remote_id)
    await billing_api.verify_subscription(authorized)
    await billing_api.transition(remote_id, "activated", emit=False)
    await billing_api.transition(remote_id, "charged", emit=False)

    counts = await billing_api.services.subscriptions.sync.run()

    assert (counts.checked, counts.repaired, counts.mismatch, counts.errors) == (1, 1, 0, 0)
    row = await billing_api.subscription_row(started["subscriptionId"])
    assert (row.status, row.paid_count) == ("active", 2)
    assert row.current_period_end is not None
    assert row.next_charge_at == row.current_period_end
    [run] = await billing_api.run_rows("subscriptions")
    assert (run.status, run.checked_count, run.repaired_count, run.mismatch_count) == ("completed", 1, 1, 0)
    assert run.finished_at is not None
    assert await billing_api.event_count() == 0
    assert await billing_api.wallet_balance(billing_api.primary_id) == 0
    again = await billing_api.services.subscriptions.sync.run()
    assert (again.checked, again.repaired) == (1, 0)


async def test_an_abandoned_checkout_expires_and_its_remote_subscription_is_cancelled(
    billing_api: BillingApi,
) -> None:
    code = await billing_api.plan_product()
    started = await billing_api.started_subscription(code)
    await billing_api.expire_order(started["orderId"])

    counts = await billing_api.services.subscriptions.finalizer.finalize()

    assert counts.expired == 1
    row = await billing_api.subscription_row(started["subscriptionId"])
    assert (row.status, row.ended_at is not None) == ("expired", True)
    order = (await billing_api.primary.get(f"/v1/billing/orders/{started['orderId']}")).json()
    assert order["status"] == "expired"
    remote = await billing_api.primary.post(
        f"/v1/_test/razorpay/subscriptions/{started['razorpaySubscriptionId']}/authorize", json={}
    )
    assert remote.status_code == 409
    retry = await billing_api.subscribe(code)
    assert retry.status_code == 201
