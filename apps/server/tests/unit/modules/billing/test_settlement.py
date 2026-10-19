from dataclasses import replace
from datetime import timedelta

import pytest
from tests.unit.modules.billing.conftest import PACK_CREDITS, PACK_PRICE, BillingHarness

from motionile.modules.billing.razorpay.fake_simulator import PaymentOutcome
from motionile.modules.billing.razorpay.models import RazorpayPayment
from motionile.modules.billing.records import OrderRecord, PaymentRecord
from motionile.modules.billing.services.decisions import (
    SettlementDecision,
    SettlementOutcome,
    SettlementResult,
    SettlementSource,
    decide_settlement,
)
from motionile.modules.billing.states import InvalidTransitionError, OrderStatus, PaymentRecordStatus

SOURCE = SettlementSource.WEBHOOK


async def settle(
    harness: BillingHarness, payment: RazorpayPayment, source: SettlementSource = SOURCE
) -> SettlementResult:
    async with harness.world.transaction() as session:
        return await harness.settlement.settle(session, payment, source)


async def attempt(harness: BillingHarness, payment: RazorpayPayment) -> SettlementResult:
    async with harness.world.transaction() as session:
        return await harness.settlement.record_attempt(session, payment)


def payment_of(harness: BillingHarness, result: SettlementResult) -> PaymentRecord:
    assert result.payment_id is not None
    return harness.billing.payments[result.payment_id]


def order_with(harness: BillingHarness, order: OrderRecord, status: OrderStatus) -> OrderRecord:
    updated = replace(order, status=status)
    harness.billing.orders[order.id] = updated
    return updated


@pytest.mark.parametrize(
    ("amount", "currency", "status", "expected"),
    [
        (PACK_PRICE, "INR", OrderStatus.CREATED, SettlementDecision.GRANT),
        (PACK_PRICE, "INR", OrderStatus.PENDING, SettlementDecision.GRANT),
        (PACK_PRICE, "INR", OrderStatus.EXPIRED, SettlementDecision.GRANT),
        (PACK_PRICE, "INR", OrderStatus.FAILED, SettlementDecision.GRANT),
        (PACK_PRICE, "INR", OrderStatus.CANCELLED, SettlementDecision.GRANT),
        (PACK_PRICE, "INR", OrderStatus.PAID, SettlementDecision.DUPLICATE),
        (PACK_PRICE - 1, "INR", OrderStatus.PENDING, SettlementDecision.AMOUNT_MISMATCH),
        (PACK_PRICE + 1, "INR", OrderStatus.PENDING, SettlementDecision.AMOUNT_MISMATCH),
        (PACK_PRICE, "USD", OrderStatus.PENDING, SettlementDecision.CURRENCY_MISMATCH),
        (PACK_PRICE - 1, "USD", OrderStatus.PENDING, SettlementDecision.CURRENCY_MISMATCH),
        (PACK_PRICE - 1, "INR", OrderStatus.PAID, SettlementDecision.AMOUNT_MISMATCH),
    ],
)
async def test_decision_table(
    billing_harness: BillingHarness, amount: int, currency: str, status: OrderStatus, expected: SettlementDecision
) -> None:
    order = replace(await billing_harness.local_order(), status=status)

    assert decide_settlement(order, amount, currency) is expected


async def test_a_captured_payment_marks_the_order_paid_and_grants_a_lot_once(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order)

    result = await settle(billing_harness, payment)

    assert result.outcome is SettlementOutcome.SETTLED
    assert result.credits_granted == PACK_CREDITS
    settled = billing_harness.billing.orders[order.id]
    assert settled.status is OrderStatus.PAID
    assert settled.paid_at == billing_harness.clock.now()
    recorded = payment_of(billing_harness, result)
    assert recorded.status is PaymentRecordStatus.CAPTURED
    assert recorded.credits_granted == PACK_CREDITS
    assert recorded.fee_paise == payment.fee
    assert recorded.tax_paise == payment.tax
    assert recorded.captured_at == billing_harness.clock.now()
    assert billing_harness.balance() == PACK_CREDITS
    lots = list(billing_harness.credits_store.lots.values())
    assert [(lot.source, lot.amount, lot.expires_at, lot.ref_type, lot.ref_id) for lot in lots] == [
        ("purchase", PACK_CREDITS, None, "payment", recorded.id)
    ]
    ledger = billing_harness.credits_store.ledger
    assert [(entry.reason, entry.delta, entry.idempotency_key) for entry in ledger] == [
        ("purchase", PACK_CREDITS, f"payment:{recorded.id}")
    ]
    assert billing_harness.audit_actions() == ["billing.order.paid"]


async def test_the_receipt_is_queued_with_the_order_details(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()

    await settle(billing_harness, await billing_harness.pay(order))

    [receipt] = billing_harness.world.receipts
    assert receipt.user_id == billing_harness.user_id
    assert receipt.product_name == "Starter"
    assert (receipt.amount_paise, receipt.currency, receipt.credits) == (PACK_PRICE, "INR", PACK_CREDITS)
    assert receipt.order_reference == str(order.id)
    assert receipt.paid_at == billing_harness.clock.now()


async def test_settling_again_changes_nothing_and_returns_the_same_ids(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order)
    first = await settle(billing_harness, payment)

    second = await settle(billing_harness, payment, SettlementSource.VERIFY)
    third = await settle(billing_harness, payment, SettlementSource.RECONCILIATION)

    assert second.outcome is third.outcome is SettlementOutcome.ALREADY_SETTLED
    assert (second.order_id, second.payment_id) == (first.order_id, first.payment_id)
    assert second.credits_granted == PACK_CREDITS
    assert billing_harness.balance() == PACK_CREDITS
    assert len(billing_harness.credits_store.ledger) == 1
    assert len(billing_harness.world.receipts) == 1
    assert len(billing_harness.billing.payments) == 1
    assert billing_harness.audit_actions() == ["billing.order.paid"]


@pytest.mark.parametrize(
    "late_status", [OrderStatus.CREATED, OrderStatus.EXPIRED, OrderStatus.FAILED, OrderStatus.CANCELLED]
)
async def test_a_late_payment_settles_orders_that_were_not_pending(
    billing_harness: BillingHarness, late_status: OrderStatus
) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order)
    order_with(billing_harness, order, late_status)

    result = await settle(billing_harness, payment)

    assert result.outcome is SettlementOutcome.SETTLED
    assert billing_harness.billing.orders[order.id].status is OrderStatus.PAID
    assert billing_harness.balance() == PACK_CREDITS
    late = [event for event in billing_harness.audit.events if event.action == "billing.order.settled_late"]
    assert (len(late) == 1) is (late_status is not OrderStatus.CREATED)
    if late:
        assert late[0].metadata["previousStatus"] == late_status.value


async def test_a_pending_order_settles_without_a_late_audit(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()

    await settle(billing_harness, await billing_harness.pay(order))

    assert "billing.order.settled_late" not in billing_harness.audit_actions()


async def test_an_amount_mismatch_is_recorded_without_credits_and_flags_the_order(
    billing_harness: BillingHarness,
) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order, amount=PACK_PRICE - 100)

    result = await settle(billing_harness, payment)

    assert result.outcome is SettlementOutcome.MISMATCH
    assert result.needs_attention
    flagged = billing_harness.billing.orders[order.id]
    assert (flagged.status, flagged.flag_reason, flagged.flagged_at) == (
        OrderStatus.PENDING,
        "amount_mismatch",
        billing_harness.clock.now(),
    )
    recorded = payment_of(billing_harness, result)
    assert (recorded.status, recorded.amount_paise, recorded.credits_granted) == (
        PaymentRecordStatus.CAPTURED,
        PACK_PRICE - 100,
        0,
    )
    assert billing_harness.balance() == 0
    assert billing_harness.credits_store.ledger == []
    assert billing_harness.world.receipts == []
    [(code, fields)] = billing_harness.world.alerts
    assert code == "billing.payment_mismatch"
    assert fields["reason"] == "amount_mismatch"
    assert fields["expected_amount_paise"] == PACK_PRICE
    assert fields["received_amount_paise"] == PACK_PRICE - 100
    assert billing_harness.audit_actions() == ["billing.payment.flagged"]


async def test_a_currency_mismatch_is_flagged_the_same_way(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order, currency="USD")

    result = await settle(billing_harness, payment)

    assert result.outcome is SettlementOutcome.MISMATCH
    assert billing_harness.billing.orders[order.id].flag_reason == "currency_mismatch"
    assert billing_harness.balance() == 0
    assert [code for code, _ in billing_harness.world.alerts] == ["billing.payment_mismatch"]


async def test_replaying_a_mismatched_payment_neither_alerts_nor_grants_again(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order, amount=PACK_PRICE + 1)
    await settle(billing_harness, payment)

    replay = await settle(billing_harness, payment)

    assert replay.outcome is SettlementOutcome.MISMATCH
    assert replay.credits_granted == 0
    assert len(billing_harness.world.alerts) == 1
    assert billing_harness.balance() == 0


async def test_a_second_captured_payment_on_a_paid_order_is_a_flagged_duplicate(
    billing_harness: BillingHarness,
) -> None:
    order = await billing_harness.open_order()
    first = await billing_harness.pay(order)
    await settle(billing_harness, first)
    duplicate = RazorpayPayment.model_validate({**first.model_dump(), "id": "pay_duplicate", "captured": True})

    result = await settle(billing_harness, duplicate)

    assert result.outcome is SettlementOutcome.DUPLICATE
    assert billing_harness.balance() == PACK_CREDITS
    assert len(billing_harness.credits_store.ledger) == 1
    paid = billing_harness.billing.orders[order.id]
    assert (paid.status, paid.flag_reason) == (OrderStatus.PAID, "duplicate_payment")
    extra = payment_of(billing_harness, result)
    assert (extra.status, extra.credits_granted) == (PaymentRecordStatus.CAPTURED, 0)
    assert [code for code, _ in billing_harness.world.alerts] == ["billing.duplicate_payment"]
    assert len(billing_harness.world.receipts) == 1


async def test_a_payment_for_an_unknown_order_is_reported_and_stores_nothing(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order)
    stray = RazorpayPayment.model_validate({**payment.model_dump(), "order_id": "order_unknown"})

    result = await settle(billing_harness, stray)

    assert result.outcome is SettlementOutcome.UNKNOWN_ORDER
    assert billing_harness.billing.payments == {}
    assert billing_harness.balance() == 0


async def test_a_payment_without_an_order_is_unknown(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order)
    orphan = RazorpayPayment.model_validate({**payment.model_dump(), "order_id": None})

    assert (await settle(billing_harness, orphan)).outcome is SettlementOutcome.UNKNOWN_ORDER


async def test_an_authorized_payment_is_recorded_then_captured_by_a_later_settlement(
    billing_harness: BillingHarness,
) -> None:
    order = await billing_harness.open_order()
    authorized = await billing_harness.pay(order, PaymentOutcome.AUTHORIZED)

    recorded = await settle(billing_harness, authorized)

    assert recorded.outcome is SettlementOutcome.ATTEMPT_RECORDED
    assert payment_of(billing_harness, recorded).status is PaymentRecordStatus.AUTHORIZED
    assert billing_harness.balance() == 0
    captured = RazorpayPayment.model_validate(
        {**authorized.model_dump(), "status": "captured", "captured": True, "fee": 398, "tax": 71}
    )

    settled = await settle(billing_harness, captured)

    assert settled.outcome is SettlementOutcome.SETTLED
    assert settled.payment_id == recorded.payment_id
    row = payment_of(billing_harness, settled)
    assert (row.status, row.fee_paise, row.tax_paise, row.credits_granted) == (
        PaymentRecordStatus.CAPTURED,
        398,
        71,
        PACK_CREDITS,
    )
    assert len(billing_harness.billing.payments) == 1


async def test_a_failed_payment_leaves_the_order_pending_and_a_later_success_settles_it(
    billing_harness: BillingHarness,
) -> None:
    order = await billing_harness.open_order()
    failed = await billing_harness.pay(order, PaymentOutcome.FAILURE)

    result = await attempt(billing_harness, failed)

    assert result.outcome is SettlementOutcome.ATTEMPT_RECORDED
    row = payment_of(billing_harness, result)
    assert (row.status, row.error_code) == (PaymentRecordStatus.FAILED, "BAD_REQUEST_ERROR")
    assert row.error_description
    assert billing_harness.billing.orders[order.id].status is OrderStatus.PENDING
    assert billing_harness.balance() == 0
    retry = RazorpayPayment.model_validate(
        {**failed.model_dump(), "id": "pay_retry", "status": "captured", "captured": True, "error_code": None}
    )

    settled = await settle(billing_harness, retry)

    assert settled.outcome is SettlementOutcome.SETTLED
    assert billing_harness.billing.orders[order.id].status is OrderStatus.PAID
    assert len(billing_harness.billing.payments) == 2


async def test_a_captured_payment_never_regresses_to_failed(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    captured = await billing_harness.pay(order)
    await settle(billing_harness, captured)
    stale_failure = RazorpayPayment.model_validate({**captured.model_dump(), "status": "failed", "captured": False})

    result = await attempt(billing_harness, stale_failure)

    assert result.outcome is SettlementOutcome.ATTEMPT_RECORDED
    row = payment_of(billing_harness, result)
    assert row.status is PaymentRecordStatus.CAPTURED
    assert row.credits_granted == PACK_CREDITS


async def test_an_authorization_that_fails_later_is_marked_failed(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    authorized = await billing_harness.pay(order, PaymentOutcome.AUTHORIZED)
    await attempt(billing_harness, authorized)
    failed = RazorpayPayment.model_validate({**authorized.model_dump(), "status": "failed", "error_code": "EXPIRED"})

    result = await attempt(billing_harness, failed)

    row = payment_of(billing_harness, result)
    assert (row.status, row.error_code) == (PaymentRecordStatus.FAILED, "EXPIRED")


async def test_a_created_payment_is_not_recordable(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order)
    created = RazorpayPayment.model_validate({**payment.model_dump(), "status": "created", "captured": False})

    assert (await attempt(billing_harness, created)).outcome is SettlementOutcome.NOT_RECORDABLE
    assert billing_harness.billing.payments == {}


async def test_a_captured_payment_cannot_resurrect_a_failed_one(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    failed = await billing_harness.pay(order, PaymentOutcome.FAILURE)
    await attempt(billing_harness, failed)
    claimed = RazorpayPayment.model_validate({**failed.model_dump(), "status": "captured", "captured": True})

    with pytest.raises(InvalidTransitionError):
        await settle(billing_harness, claimed)

    assert billing_harness.balance() == 0


async def test_a_failed_settlement_rolls_everything_back(
    billing_harness: BillingHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order)

    async def explode(*_: object, **__: object) -> None:
        raise RuntimeError("receipt queue unavailable")

    monkeypatch.setattr(billing_harness.settlement, "_receipts", explode)

    with pytest.raises(RuntimeError, match="receipt queue"):
        await settle(billing_harness, payment)

    assert billing_harness.billing.orders[order.id].status is OrderStatus.PENDING
    assert billing_harness.billing.payments == {}
    assert billing_harness.credits_store.ledger == []
    assert billing_harness.balance() == 0


async def test_each_settlement_source_is_audited(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()

    await settle(billing_harness, await billing_harness.pay(order), SettlementSource.RECONCILIATION)

    [event] = billing_harness.audit.events
    assert event.metadata["source"] == "reconciliation"
    assert event.target_type == "order"
    assert event.target_id == str(order.id)
    assert event.metadata["userId"] == str(billing_harness.user_id)


async def test_the_clock_drives_paid_at(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order)
    billing_harness.clock.advance(timedelta(hours=3))

    await settle(billing_harness, payment)

    assert billing_harness.billing.orders[order.id].paid_at == billing_harness.clock.now()
