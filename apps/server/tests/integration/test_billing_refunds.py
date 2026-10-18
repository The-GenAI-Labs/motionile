import asyncio
from typing import Any
from uuid import UUID

from sqlalchemy import text
from tests.integration.billing_support import (
    PACK_CREDITS,
    PACK_PRICE,
    SUBSCRIPTION_CREDITS,
    SUBSCRIPTION_PRICE,
    BillingApi,
)

from motionile.core.errors import PROBLEM_MEDIA_TYPE
from motionile.core.ids import new_id
from motionile.modules.access import invalidate_user_access
from motionile.modules.billing.razorpay.factory import razorpay_for
from motionile.modules.billing.razorpay.fake import FakeRazorpay
from motionile.modules.billing.razorpay.models import RefundStatus as RemoteRefundStatus
from motionile.modules.credits import ReserveCommand


async def paid_pack(api: BillingApi) -> UUID:
    checkout = await api.checkout()
    paid = await api.pay(checkout["razorpayOrderId"])
    response = await api.verify(paid)
    assert response.status_code == 200, response.text
    [payment] = await api.payment_rows()
    return payment.id


async def make_admin(api: BillingApi, role: str = "super_admin") -> None:
    await api.grant_role(api.other_id, role)


async def refund_via_api(api: BillingApi, payment_id: UUID, amount: int | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"reason": "Customer asked for it"}
    if amount is not None:
        body["amountPaise"] = amount
    response = await api.create_refund(payment_id, body)
    assert response.status_code == 201, response.text
    payload: dict[str, Any] = response.json()
    return payload


async def process_refund(api: BillingApi, refund: dict[str, Any], outcome: str = "processed") -> None:
    await api.settle_remote_refund(refund["razorpayRefundId"], outcome)
    await api.deliver(event=f"refund.{outcome}", refundId=refund["razorpayRefundId"])
    await api.process_dispatched()


async def spend(api: BillingApi, amount: int) -> None:
    ref_id = new_id()
    async with api.database.transaction() as session:
        reservation = await api.credits.reserve(
            session,
            ReserveCommand(
                user_id=api.primary_id, amount=amount, ref_type="job", ref_id=ref_id, key=f"reserve-{ref_id}"
            ),
        )
        await api.credits.commit(session, reservation.id, amount, f"commit-{ref_id}")


async def remote_refund_count(api: BillingApi, payment_id: UUID) -> int:
    [payment] = [item for item in await api.payment_rows() if item.id == payment_id]
    return len(await razorpay_for(api.resources).list_payment_refunds(payment.razorpay_payment_id))


async def test_only_a_super_admin_holds_the_refund_permission_by_default(billing_api: BillingApi) -> None:
    payment_id = await paid_pack(billing_api)
    body = {"amountPaise": 1_000, "reason": "Test"}

    as_user = await billing_api.create_refund(payment_id, body, billing_api.primary)
    await make_admin(billing_api, "admin")
    as_admin = await billing_api.create_refund(payment_id, body)
    await billing_api.revoke_roles(billing_api.other_id)
    await make_admin(billing_api, "super_admin")
    as_super_admin = await billing_api.create_refund(payment_id, body)
    anonymous = await billing_api.anonymous.post(
        f"/v1/admin/billing/payments/{payment_id}/refunds", json=body, headers={"Idempotency-Key": billing_api.keys()}
    )

    assert as_user.status_code == 403
    assert as_admin.status_code == 403
    assert as_admin.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert as_super_admin.status_code == 201, as_super_admin.text
    assert anonymous.status_code in {401, 403}
    assert len(await billing_api.refund_rows()) == 1


async def test_an_admin_granted_the_permission_can_refund(billing_api: BillingApi) -> None:
    payment_id = await paid_pack(billing_api)
    await make_admin(billing_api, "admin")
    grant = (
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT roles.id, permissions.id FROM roles CROSS JOIN permissions "
        "WHERE roles.key = 'admin' AND permissions.key = 'billing.refunds.create' ON CONFLICT DO NOTHING"
    )
    revoke = (
        "DELETE FROM role_permissions WHERE role_id = (SELECT id FROM roles WHERE key = 'admin') "
        "AND permission_id = (SELECT id FROM permissions WHERE key = 'billing.refunds.create')"
    )
    async with billing_api.database.transaction() as session:
        await session.execute(text(grant))
    try:
        await invalidate_user_access(billing_api.resources.redis_store, billing_api.other_id)

        response = await billing_api.create_refund(payment_id, {"reason": "Granted"})

        assert response.status_code == 201, response.text
    finally:
        async with billing_api.database.transaction() as session:
            await session.execute(text(revoke))


async def test_a_partial_refund_flows_from_request_to_proportional_clawback(billing_api: BillingApi) -> None:
    payment_id = await paid_pack(billing_api)
    await make_admin(billing_api)

    refund = await refund_via_api(billing_api, payment_id, PACK_PRICE // 2)

    assert set(refund) == {
        "id",
        "status",
        "amountPaise",
        "reason",
        "creditsClawedBack",
        "razorpayRefundId",
        "createdAt",
    }
    assert (refund["status"], refund["amountPaise"], refund["creditsClawedBack"]) == ("pending", PACK_PRICE // 2, 0)
    assert refund["reason"] == "Customer asked for it"
    assert refund["razorpayRefundId"].startswith("rfnd_")
    assert await billing_api.wallet_balance(billing_api.primary_id) == PACK_CREDITS

    await billing_api.deliver(event="refund.created", refundId=refund["razorpayRefundId"])
    await billing_api.process_dispatched()
    await process_refund(billing_api, refund)

    [row] = await billing_api.refund_rows()
    assert (row.status, row.credits_clawed_back, row.processed_at is not None) == ("processed", 50, True)
    [payment] = await billing_api.payment_rows()
    assert (payment.status, payment.refunded_paise) == ("partially_refunded", PACK_PRICE // 2)
    assert await billing_api.wallet_balance(billing_api.primary_id) == PACK_CREDITS - 50
    assert (await billing_api.ledger_rows(billing_api.primary_id))[-1] == ("refund_clawback", -50, f"refund:{row.id}")
    assert billing_api.recorded.notice_templates() == ["refund_processed"]
    assert billing_api.recorded.notices[0].context["credits_recovered"] == "50"
    history = (await billing_api.primary.get("/v1/billing/history")).json()["items"]
    assert [item["type"] for item in history if item["type"] == "refund"] == ["refund"]
    assert {"billing.refund.requested", "billing.refund.processed"} <= set(await billing_api.audit_actions())
    async with billing_api.database.transaction() as session:
        actor = await session.scalar(
            text("SELECT actor_user_id FROM audit_log WHERE action = 'billing.refund.requested'")
        )
    assert actor == billing_api.other_id


async def test_a_refund_claws_back_only_what_is_unspent_and_a_spent_lot_claws_back_nothing(
    billing_api: BillingApi,
) -> None:
    payment_id = await paid_pack(billing_api)
    await make_admin(billing_api)
    await spend(billing_api, 80)

    first = await refund_via_api(billing_api, payment_id, PACK_PRICE // 2)
    await process_refund(billing_api, first)

    assert (await billing_api.refund_rows())[0].credits_clawed_back == 20
    assert await billing_api.wallet_balance(billing_api.primary_id) == 0
    ledger_rows = len(await billing_api.ledger_rows(billing_api.primary_id))

    second = await refund_via_api(billing_api, payment_id)
    await process_refund(billing_api, second)

    rows = await billing_api.refund_rows()
    assert [row.credits_clawed_back for row in rows] == [20, 0]
    assert len(await billing_api.ledger_rows(billing_api.primary_id)) == ledger_rows
    [payment] = await billing_api.payment_rows()
    assert (payment.status, payment.refunded_paise) == ("refunded", PACK_PRICE)


async def test_a_duplicate_refund_processed_event_changes_nothing(billing_api: BillingApi) -> None:
    payment_id = await paid_pack(billing_api)
    await make_admin(billing_api)
    refund = await refund_via_api(billing_api, payment_id, PACK_PRICE // 2)
    await process_refund(billing_api, refund)
    ledger_before = await billing_api.ledger_rows(billing_api.primary_id)

    await billing_api.deliver(event="refund.processed", refundId=refund["razorpayRefundId"])
    await billing_api.deliver(
        event="refund.processed", refundId=refund["razorpayRefundId"], eventId="evt_again", repeat=3
    )
    await billing_api.process_dispatched()

    assert await billing_api.ledger_rows(billing_api.primary_id) == ledger_before
    [payment] = await billing_api.payment_rows()
    assert payment.refunded_paise == PACK_PRICE // 2
    assert len(billing_api.recorded.notices) == 1
    assert all(event.status == "processed" for event in await billing_api.event_rows())


async def test_a_failed_refund_is_recorded_and_alerted(billing_api: BillingApi) -> None:
    payment_id = await paid_pack(billing_api)
    await make_admin(billing_api)
    refund = await refund_via_api(billing_api, payment_id)

    await process_refund(billing_api, refund, "failed")

    [row] = await billing_api.refund_rows()
    assert (row.status, row.processed_at) == ("failed", None)
    assert row.failure_reason
    [payment] = await billing_api.payment_rows()
    assert (payment.status, payment.refunded_paise) == ("captured", 0)
    assert await billing_api.wallet_balance(billing_api.primary_id) == PACK_CREDITS
    assert "billing.refund_failed" in billing_api.recorded.alert_codes()
    retry = await refund_via_api(billing_api, payment_id)
    assert retry["amountPaise"] == PACK_PRICE


async def test_refunds_that_together_exceed_the_payment_are_refused(billing_api: BillingApi) -> None:
    payment_id = await paid_pack(billing_api)
    await make_admin(billing_api)
    await refund_via_api(billing_api, payment_id, 15_000)

    refused = await billing_api.create_refund(payment_id, {"amountPaise": 5_000, "reason": "Too much"})

    assert refused.status_code == 422
    assert refused.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert refused.json()["code"] == "refund_exceeds_refundable"
    assert refused.json()["refundablePaise"] == PACK_PRICE - 15_000
    assert len(await billing_api.refund_rows()) == 1
    assert await remote_refund_count(billing_api, payment_id) == 1


async def test_concurrent_refunds_cannot_exceed_the_payment(billing_api: BillingApi) -> None:
    payment_id = await paid_pack(billing_api)
    await make_admin(billing_api)
    body = {"amountPaise": 12_000, "reason": "Concurrent"}

    responses = await asyncio.gather(
        billing_api.create_refund(payment_id, body),
        billing_api.create_refund(payment_id, body),
        billing_api.create_refund(payment_id, body),
    )

    assert sorted(response.status_code for response in responses) == [201, 422, 422]
    assert {response.json()["code"] for response in responses if response.status_code == 422} == {
        "refund_exceeds_refundable"
    }
    rows = await billing_api.refund_rows()
    assert len(rows) == 1
    assert sum(row.amount_paise for row in rows) <= PACK_PRICE
    assert await remote_refund_count(billing_api, payment_id) == 1


async def test_concurrent_partial_refunds_that_fit_are_all_accepted(billing_api: BillingApi) -> None:
    payment_id = await paid_pack(billing_api)
    await make_admin(billing_api)

    responses = await asyncio.gather(
        *[billing_api.create_refund(payment_id, {"amountPaise": 4_000, "reason": f"Part {n}"}) for n in range(4)]
    )

    assert [response.status_code for response in responses] == [201, 201, 201, 201]
    assert sum(row.amount_paise for row in await billing_api.refund_rows()) == 16_000
    extra = await billing_api.create_refund(payment_id, {"amountPaise": 4_000, "reason": "Part 5"})
    assert extra.status_code == 422
    assert extra.json()["refundablePaise"] == PACK_PRICE - 16_000


async def test_creating_a_refund_needs_an_idempotency_key_and_replays_safely(billing_api: BillingApi) -> None:
    payment_id = await paid_pack(billing_api)
    await make_admin(billing_api)
    body = {"amountPaise": 5_000, "reason": "Once"}
    csrf_headers = {
        key: value for key, value in billing_api.headers(billing_api.other).items() if key.lower() != "idempotency-key"
    }
    missing = await billing_api.other.post(
        f"/v1/admin/billing/payments/{payment_id}/refunds", json=body, headers=csrf_headers
    )
    key = billing_api.keys()

    first = await billing_api.create_refund(payment_id, body, key=key)
    replayed = await billing_api.create_refund(payment_id, body, key=key)
    reused = await billing_api.create_refund(payment_id, {**body, "amountPaise": 6_000}, key=key)

    assert (missing.status_code, missing.json()["code"]) == (400, "idempotency_key_required")
    assert first.status_code == 201
    assert replayed.headers["idempotent-replayed"] == "true"
    assert replayed.json() == first.json()
    assert reused.status_code == 409
    assert len(await billing_api.refund_rows()) == 1
    assert await remote_refund_count(billing_api, payment_id) == 1


async def test_a_provider_timeout_after_the_refund_is_recovered_without_a_second_refund(
    billing_api: BillingApi,
) -> None:
    payment_id = await paid_pack(billing_api)
    await make_admin(billing_api)
    await billing_api.arm_fault("create_refund", "timeout_after_create")

    response = await billing_api.create_refund(payment_id, {"amountPaise": 5_000, "reason": "Timeout"})

    assert response.status_code == 201, response.text
    assert response.json()["razorpayRefundId"] is not None
    assert await remote_refund_count(billing_api, payment_id) == 1


async def test_a_provider_timeout_before_the_refund_is_never_resent(billing_api: BillingApi) -> None:
    payment_id = await paid_pack(billing_api)
    await make_admin(billing_api)
    await billing_api.arm_fault("create_refund", "timeout_before_create")

    response = await billing_api.create_refund(payment_id, {"amountPaise": 5_000, "reason": "Outage"})

    assert response.status_code == 503
    assert response.json()["code"] == "payment_provider_unavailable"
    [row] = await billing_api.refund_rows()
    assert (row.status, row.razorpay_refund_id) == ("pending", None)
    assert await remote_refund_count(billing_api, payment_id) == 0
    assert "billing.refund_unconfirmed" in billing_api.recorded.alert_codes()
    again = await billing_api.create_refund(payment_id, {"reason": "Everything left"})
    assert again.status_code == 201
    assert again.json()["amountPaise"] == PACK_PRICE - 5_000


async def test_a_provider_that_already_processed_the_refund_settles_it_in_the_same_request(
    billing_api: BillingApi,
) -> None:
    payment_id = await paid_pack(billing_api)
    await make_admin(billing_api)
    fake = razorpay_for(billing_api.resources)
    assert isinstance(fake, FakeRazorpay)
    fake.refund_initial_status = RemoteRefundStatus.PROCESSED

    response = await billing_api.create_refund(payment_id, {"amountPaise": PACK_PRICE // 2, "reason": "Instant"})

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["status"], body["creditsClawedBack"]) == ("processed", 50)
    assert await billing_api.wallet_balance(billing_api.primary_id) == PACK_CREDITS - 50


async def test_refund_requests_are_validated(billing_api: BillingApi) -> None:
    payment_id = await paid_pack(billing_api)
    await make_admin(billing_api)

    cases: list[dict[str, Any]] = [
        {"reason": ""},
        {"reason": "   "},
        {"reason": "x" * 501},
        {},
        {"amountPaise": 0, "reason": "zero"},
        {"amountPaise": -5, "reason": "negative"},
        {"amountPaise": 1.5, "reason": "fraction"},
        {"reason": "extra", "userId": str(billing_api.primary_id)},
    ]
    responses = [await billing_api.create_refund(payment_id, body) for body in cases]
    unknown = await billing_api.create_refund(new_id(), {"reason": "No such payment"})
    malformed = await billing_api.other.post(
        "/v1/admin/billing/payments/not-a-uuid/refunds",
        json={"reason": "x"},
        headers=billing_api.headers(billing_api.other),
    )

    assert [response.status_code for response in responses] == [422] * len(cases)
    assert (unknown.status_code, unknown.json()["code"]) == (404, "payment_not_found")
    assert malformed.status_code == 422
    assert await billing_api.refund_rows() == []


async def test_a_payment_that_is_not_captured_cannot_be_refunded(billing_api: BillingApi) -> None:
    checkout = await billing_api.checkout()
    paid = await billing_api.pay(checkout["razorpayOrderId"], outcome="authorized")
    paid["razorpay_signature"] = billing_api.sign(paid["razorpay_order_id"], paid["razorpay_payment_id"])
    await billing_api.verify(paid)
    [payment] = await billing_api.payment_rows()
    assert payment.status == "authorized"
    await make_admin(billing_api)

    response = await billing_api.create_refund(payment.id, {"reason": "Not captured"})

    assert (response.status_code, response.json()["code"]) == (409, "payment_not_refundable")
    assert await billing_api.refund_rows() == []


async def test_a_rejected_refund_is_marked_failed_and_alerted(billing_api: BillingApi) -> None:
    payment_id = await paid_pack(billing_api)
    await make_admin(billing_api)
    [payment] = await billing_api.payment_rows()
    await razorpay_for(billing_api.resources).create_refund(payment.razorpay_payment_id, amount=PACK_PRICE)

    response = await billing_api.create_refund(payment_id, {"amountPaise": 5_000, "reason": "Already refunded"})

    assert response.status_code == 422
    assert response.json()["code"] == "refund_rejected"
    [row] = await billing_api.refund_rows()
    assert row.status == "failed"
    assert row.failure_reason
    assert "billing.refund_rejected" in billing_api.recorded.alert_codes()


async def test_refunding_a_subscription_payment_keeps_the_subscription(billing_api: BillingApi) -> None:
    code = await billing_api.plan_product()
    started = await billing_api.activate_subscription(code)
    await make_admin(billing_api)
    [payment] = await billing_api.payment_rows()

    refund = await refund_via_api(billing_api, payment.id, SUBSCRIPTION_PRICE // 2)
    await process_refund(billing_api, refund)

    row = (await billing_api.refund_rows())[0]
    assert row.credits_clawed_back == SUBSCRIPTION_CREDITS // 2
    assert await billing_api.wallet_balance(billing_api.primary_id) == SUBSCRIPTION_CREDITS - SUBSCRIPTION_CREDITS // 2
    subscription = await billing_api.subscription_row(started["subscriptionId"])
    assert (subscription.status, subscription.cancel_at_period_end) == ("active", False)
    assert (await billing_api.get_subscription())["subscription"]["status"] == "active"


async def test_a_refund_the_provider_reports_without_our_knowledge_is_ignored_and_alerted(
    billing_api: BillingApi,
) -> None:
    payment_id = await paid_pack(billing_api)
    [payment] = await billing_api.payment_rows()
    outside = await razorpay_for(billing_api.resources).create_refund(payment.razorpay_payment_id, amount=5_000)

    await billing_api.deliver(event="refund.processed", refundId=outside.id)
    await billing_api.process_dispatched()

    [event] = await billing_api.event_rows()
    assert (event.status, event.ignored_reason) == ("ignored", "unknown_entity")
    assert "billing.unknown_refund" in billing_api.recorded.alert_codes()
    assert payment.id == payment_id
