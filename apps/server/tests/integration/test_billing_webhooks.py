import asyncio
from typing import Any

import orjson
import pytest
from sqlalchemy import text
from tests.integration.billing_support import PACK_CREDITS, PACK_PRICE, BillingApi, client_for

from motionile.core.errors import PROBLEM_MEDIA_TYPE
from motionile.modules.billing.razorpay.factory import razorpay_for
from motionile.modules.billing.services.webhook_processor import ProcessingState

CAPTURED_AND_PAID = ["payment.captured", "order.paid"]


async def checkout_and_pay(api: BillingApi, **pay: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    checkout = await api.checkout()
    return checkout, await api.pay(checkout["razorpayOrderId"], **pay)


async def test_signed_payment_webhooks_are_stored_queued_and_settle_the_order_once(billing_api: BillingApi) -> None:
    checkout, paid = await checkout_and_pay(billing_api, webhooks=CAPTURED_AND_PAID)

    assert [item["statusCodes"] for item in paid["webhooks"]] == [[200], [200]]
    events = await billing_api.event_rows()
    assert sorted(event.event_type for event in events) == ["order.paid", "payment.captured"]
    assert all(event.status == "received" and event.attempts == 0 for event in events)
    assert len(billing_api.recorded.dispatched) == 2
    assert await billing_api.wallet_balance(billing_api.primary_id) == 0

    await billing_api.process_dispatched()

    assert (await billing_api.order_row(checkout["orderId"])).status == "paid"
    assert await billing_api.wallet_balance(billing_api.primary_id) == PACK_CREDITS
    assert len(await billing_api.ledger_rows(billing_api.primary_id)) == 1
    assert [(event.status, event.attempts) for event in await billing_api.event_rows()] == [("processed", 1)] * 2
    assert len(billing_api.recorded.receipts) == 1


async def test_a_duplicate_delivery_is_acknowledged_without_a_new_row_task_or_grant(billing_api: BillingApi) -> None:
    checkout, paid = await checkout_and_pay(billing_api)
    first = await billing_api.deliver(
        event="payment.captured",
        orderId=checkout["razorpayOrderId"],
        paymentId=paid["razorpay_payment_id"],
        eventId="evt_fixed_1",
        repeat=4,
    )

    assert first["statusCodes"] == [200, 200, 200, 200]
    assert await billing_api.event_count() == 1
    assert len(billing_api.recorded.dispatched) == 1
    await billing_api.process_dispatched()
    await billing_api.deliver(
        event="payment.captured",
        orderId=checkout["razorpayOrderId"],
        paymentId=paid["razorpay_payment_id"],
        eventId="evt_fixed_1",
    )
    assert await billing_api.event_count() == 1
    assert billing_api.recorded.dispatched == []
    assert await billing_api.wallet_balance(billing_api.primary_id) == PACK_CREDITS
    assert len(await billing_api.ledger_rows(billing_api.primary_id)) == 1


async def test_a_replayed_event_id_answers_duplicate(billing_api: BillingApi) -> None:
    document: dict[str, Any] = {"event": "account.updated", "created_at": 1_760_000_000, "payload": {}}

    first = await billing_api.post_webhook(document, event_id="evt_replay")
    second = await billing_api.post_webhook(document, event_id="evt_replay")

    assert (first.status_code, first.json()) == (200, {"status": "received"})
    assert (second.status_code, second.json()) == (200, {"status": "duplicate"})
    assert await billing_api.event_count() == 1
    assert len(billing_api.recorded.dispatched) == 1


async def test_missing_or_invalid_signatures_are_rejected_and_nothing_is_stored(billing_api: BillingApi) -> None:
    document: dict[str, Any] = {"event": "payment.captured", "payload": {}}
    body = orjson.dumps(document)

    missing = await billing_api.post_webhook(document, event_id="evt_1", sign=False)
    wrong = await billing_api.post_webhook(document, event_id="evt_1", signature="0" * 64)
    malformed = await billing_api.post_webhook(document, event_id="evt_1", signature="not-hex")
    tampered = await billing_api.post_webhook(
        body.replace(b"captured", b"failed"), event_id="evt_1", signature=billing_api.sign_webhook_body(body)
    )

    for response in (missing, wrong, malformed, tampered):
        assert response.status_code == 401
        assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
        assert response.json()["code"] == "invalid_webhook_signature"
        assert response.json()["type"] == "urn:motionile:problem:invalid_webhook_signature"
    assert await billing_api.event_count() == 0
    assert billing_api.recorded.dispatched == []


async def test_an_invalid_signature_from_the_provider_simulator_is_rejected(billing_api: BillingApi) -> None:
    checkout, paid = await checkout_and_pay(billing_api)

    delivery = await billing_api.deliver(
        event="payment.captured",
        orderId=checkout["razorpayOrderId"],
        paymentId=paid["razorpay_payment_id"],
        validSignature=False,
    )

    assert delivery["statusCodes"] == [401]
    assert await billing_api.event_count() == 0


async def test_malformed_event_ids_and_bodies_are_bad_requests(billing_api: BillingApi) -> None:
    document: dict[str, Any] = {"event": "payment.captured", "payload": {}}

    no_event_id = await billing_api.post_webhook(document)
    bad_event_id = await billing_api.post_webhook(document, event_id="has space")
    not_json = await billing_api.post_webhook(b"not json", event_id="evt_1")
    no_event = await billing_api.post_webhook({"payload": {}}, event_id="evt_2")

    assert (no_event_id.status_code, no_event_id.json()["code"]) == (400, "webhook_event_id_missing")
    assert bad_event_id.status_code == 400
    assert (not_json.status_code, not_json.json()["code"]) == (400, "invalid_webhook_payload")
    assert (no_event.status_code, no_event.json()["code"]) == (400, "invalid_webhook_payload")
    assert await billing_api.event_count() == 0


async def test_the_webhook_needs_no_session_csrf_origin_or_turnstile(billing_api: BillingApi) -> None:
    bare = client_for(billing_api.app)
    bare.headers.clear()
    async with bare:
        accepted = await billing_api.post_webhook(
            {"event": "account.updated", "payload": {}}, event_id="evt_bare", client=bare
        )
    foreign = client_for(billing_api.app)
    foreign.headers.update({"Origin": "https://evil.example"})
    async with foreign:
        from_elsewhere = await billing_api.post_webhook(
            {"event": "account.updated", "payload": {}}, event_id="evt_foreign", client=foreign
        )

    assert (accepted.status_code, from_elsewhere.status_code) == (200, 200)
    assert await billing_api.event_count() == 2


async def test_unhandled_event_types_are_stored_then_ignored(billing_api: BillingApi) -> None:
    await billing_api.post_webhook({"event": "account.updated", "payload": {}}, event_id="evt_unhandled")

    await billing_api.process_dispatched()

    [event] = await billing_api.event_rows()
    assert (event.status, event.ignored_reason, event.attempts) == ("ignored", "unhandled_event", 1)
    assert event.processed_at is not None


async def test_a_late_payment_settles_an_expired_order_and_is_audited(billing_api: BillingApi) -> None:
    checkout = await billing_api.checkout()
    async with billing_api.database.transaction() as session:
        await session.execute(text("UPDATE orders SET status = 'expired'"))
    paid = await billing_api.pay(checkout["razorpayOrderId"], webhooks=["payment.captured"])
    assert paid["webhooks"]

    await billing_api.process_dispatched()

    order = await billing_api.order_row(checkout["orderId"])
    assert order.status == "paid"
    assert order.paid_at is not None
    assert await billing_api.wallet_balance(billing_api.primary_id) == PACK_CREDITS
    assert await billing_api.audit_actions() == ["billing.order.paid", "billing.order.settled_late"]


async def test_a_mismatched_webhook_payment_is_recorded_without_credits_flagged_and_alerted(
    billing_api: BillingApi,
) -> None:
    checkout, _ = await checkout_and_pay(billing_api, amountPaise=PACK_PRICE + 500, webhooks=["payment.captured"])

    await billing_api.process_dispatched()

    order = await billing_api.order_row(checkout["orderId"])
    assert (order.status, order.flag_reason) == ("pending", "amount_mismatch")
    [payment] = await billing_api.payment_rows()
    assert (payment.amount_paise, payment.credits_granted) == (PACK_PRICE + 500, 0)
    assert await billing_api.wallet_balance(billing_api.primary_id) == 0
    [(code, fields)] = billing_api.recorded.alerts
    assert code == "billing.payment_mismatch"
    assert fields["order_id"] == checkout["orderId"]
    assert [(event.status, event.ignored_reason) for event in await billing_api.event_rows()] == [("processed", None)]


async def test_a_currency_mismatch_is_held_for_review(billing_api: BillingApi) -> None:
    checkout, _ = await checkout_and_pay(billing_api, currency="USD", webhooks=["payment.captured"])

    await billing_api.process_dispatched()

    assert (await billing_api.order_row(checkout["orderId"])).flag_reason == "currency_mismatch"
    assert await billing_api.wallet_balance(billing_api.primary_id) == 0


async def test_a_second_captured_payment_on_a_paid_order_grants_nothing_and_flags_the_order(
    billing_api: BillingApi,
) -> None:
    checkout, paid = await checkout_and_pay(billing_api)
    await billing_api.verify(paid)
    extra_payment = await billing_api.add_captured_payment(checkout["razorpayOrderId"])

    await billing_api.deliver(event="payment.captured", orderId=checkout["razorpayOrderId"], paymentId=extra_payment)
    await billing_api.process_dispatched()

    order = await billing_api.order_row(checkout["orderId"])
    assert (order.status, order.flag_reason) == ("paid", "duplicate_payment")
    payments = await billing_api.payment_rows()
    assert sorted(payment.credits_granted for payment in payments) == [0, PACK_CREDITS]
    assert await billing_api.wallet_balance(billing_api.primary_id) == PACK_CREDITS
    assert len(await billing_api.ledger_rows(billing_api.primary_id)) == 1
    assert [code for code, _ in billing_api.recorded.alerts] == ["billing.duplicate_payment"]
    assert len(billing_api.recorded.receipts) == 1


async def test_a_failed_payment_leaves_the_order_pending_and_a_later_success_settles_it(
    billing_api: BillingApi,
) -> None:
    checkout, _ = await checkout_and_pay(billing_api, outcome="failure", webhooks=["payment.failed"])
    await billing_api.process_dispatched()

    pending = await billing_api.order_row(checkout["orderId"])
    [failed] = await billing_api.payment_rows()
    assert (pending.status, failed.status, failed.credits_granted) == ("pending", "failed", 0)
    assert failed.error_code
    assert await billing_api.wallet_balance(billing_api.primary_id) == 0

    await billing_api.pay(checkout["razorpayOrderId"], webhooks=["payment.captured"])
    await billing_api.process_dispatched()

    assert (await billing_api.order_row(checkout["orderId"])).status == "paid"
    assert sorted(payment.status for payment in await billing_api.payment_rows()) == ["captured", "failed"]
    assert await billing_api.wallet_balance(billing_api.primary_id) == PACK_CREDITS


async def test_a_webhook_for_an_order_we_did_not_create_is_ignored_as_an_unknown_entity(
    billing_api: BillingApi,
) -> None:
    remote = await razorpay_for(billing_api.resources).create_order(
        amount=PACK_PRICE, currency="INR", receipt="not-ours"
    )
    await billing_api.pay(remote.id, webhooks=["payment.captured"])

    await billing_api.process_dispatched()

    [event] = await billing_api.event_rows()
    assert (event.status, event.ignored_reason) == ("ignored", "unknown_entity")
    assert await billing_api.payment_rows() == []


async def test_the_captured_and_order_paid_events_together_grant_once_even_processed_twice(
    billing_api: BillingApi,
) -> None:
    await checkout_and_pay(billing_api, webhooks=CAPTURED_AND_PAID)
    ids = [event_id for event_id, _ in billing_api.recorded.dispatched]

    for event_id in ids * 2:
        await billing_api.services.processor.process(event_id)

    assert await billing_api.wallet_balance(billing_api.primary_id) == PACK_CREDITS
    assert len(await billing_api.ledger_rows(billing_api.primary_id)) == 1
    assert [event.attempts for event in await billing_api.event_rows()] == [1, 1]


@pytest.mark.slow
async def test_verify_and_webhook_settling_the_same_payment_concurrently_grant_exactly_once(
    billing_api: BillingApi,
) -> None:
    repetitions = 5
    for _ in range(repetitions):
        billing_api.recorded.dispatched.clear()
        checkout, paid = await checkout_and_pay(billing_api, webhooks=CAPTURED_AND_PAID)
        event_ids = [event_id for event_id, _ in billing_api.recorded.dispatched]
        billing_api.recorded.dispatched.clear()

        verifies, processed = await asyncio.gather(
            asyncio.gather(*(billing_api.verify(paid, key=billing_api.keys()) for _ in range(3))),
            asyncio.gather(*(billing_api.services.processor.process(event_id) for event_id in event_ids)),
        )

        assert [response.status_code for response in verifies] == [200, 200, 200]
        assert {response.json()["status"] for response in verifies} == {"paid"}
        assert {response.json()["creditsGranted"] for response in verifies} == {PACK_CREDITS}
        assert all(result.state is ProcessingState.PROCESSED for result in processed)
        assert (await billing_api.order_row(checkout["orderId"])).status == "paid"

    assert await billing_api.wallet_balance(billing_api.primary_id) == repetitions * PACK_CREDITS
    assert len(await billing_api.ledger_rows(billing_api.primary_id)) == repetitions
    assert len(billing_api.recorded.receipts) == repetitions
    payments = await billing_api.payment_rows()
    assert [payment.credits_granted for payment in payments] == [PACK_CREDITS] * repetitions
    async with billing_api.database.transaction() as session:
        lots = (await session.execute(text("SELECT count(*), sum(amount), sum(remaining) FROM credit_lots"))).one()
    assert tuple(lots) == (repetitions, repetitions * PACK_CREDITS, repetitions * PACK_CREDITS)


@pytest.mark.slow
async def test_concurrent_settlements_of_different_orders_for_one_user_do_not_deadlock(
    billing_api: BillingApi,
) -> None:
    first, second = await billing_api.checkout(), await billing_api.checkout()
    paid_first = await billing_api.pay(first["razorpayOrderId"])
    paid_second = await billing_api.pay(second["razorpayOrderId"])

    responses = await asyncio.gather(
        billing_api.verify(paid_first), billing_api.verify(paid_second), billing_api.verify(paid_first)
    )

    assert [response.status_code for response in responses] == [200, 200, 200]
    assert await billing_api.wallet_balance(billing_api.primary_id) == 2 * PACK_CREDITS
    assert len(await billing_api.ledger_rows(billing_api.primary_id)) == 2


async def test_concurrent_deliveries_of_one_event_store_it_once(billing_api: BillingApi) -> None:
    document: dict[str, Any] = {"event": "account.updated", "payload": {}}

    responses = await asyncio.gather(*(billing_api.post_webhook(document, event_id="evt_race") for _ in range(6)))

    assert [response.status_code for response in responses] == [200] * 6
    assert sorted(response.json()["status"] for response in responses).count("received") == 1
    assert await billing_api.event_count() == 1
    assert len(billing_api.recorded.dispatched) == 1
