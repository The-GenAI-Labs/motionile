from dataclasses import replace
from uuid import UUID

import pytest
from tests.unit.modules.billing.conftest import PACK_CREDITS, PACK_PRICE, BillingHarness
from tests.unit.modules.billing.subscription_support import PLAN_CREDITS, PLAN_PRICE, SubscriptionHarness

from motionile.core.ids import new_id
from motionile.modules.billing.exceptions import (
    PaymentNotFoundError,
    PaymentNotRefundableError,
    PaymentProviderUnavailableError,
    RefundExceedsRefundableError,
    RefundRejectedError,
)
from motionile.modules.billing.razorpay.fake_events import WebhookEventName
from motionile.modules.billing.razorpay.fake_simulator import RefundOutcome
from motionile.modules.billing.razorpay.fake_store import EntityKind, FaultKind, FaultOperation
from motionile.modules.billing.razorpay.models import RefundStatus as RemoteRefundStatus
from motionile.modules.billing.records import PaymentRecord, RefundRecord
from motionile.modules.billing.services.refunds import CreateRefundCommand
from motionile.modules.billing.services.settlement import SettlementSource
from motionile.modules.billing.services.webhook_processor import ProcessingState
from motionile.modules.billing.states import PaymentRecordStatus, RefundStatus, SubscriptionStatus
from motionile.modules.credits import ReserveCommand

ADMIN_ID = new_id()


@pytest.fixture
def subscription_harness(billing_harness: BillingHarness) -> SubscriptionHarness:
    return SubscriptionHarness(billing_harness)


async def captured_pack_payment(harness: SubscriptionHarness) -> PaymentRecord:
    base = harness.base
    order = await base.open_order()
    payment = await base.pay(order)
    async with base.world.transaction() as session:
        result = await base.settlement.settle(session, payment, SettlementSource.WEBHOOK)
    assert result.payment_id is not None
    return base.billing.payments[result.payment_id]


async def spend(harness: SubscriptionHarness, amount: int) -> None:
    base = harness.base
    ref_id = new_id()
    async with base.world.transaction() as session:
        reservation = await base.credits.reserve(
            session,
            ReserveCommand(user_id=base.user_id, amount=amount, ref_type="job", ref_id=ref_id, key=f"r-{ref_id}"),
        )
        await base.credits.commit(session, reservation.id, amount, f"c-{ref_id}")


def command(
    payment_id: UUID, amount: int | None = None, reason: str = "Customer request", key: str | None = None
) -> CreateRefundCommand:
    return CreateRefundCommand(
        admin_id=ADMIN_ID, payment_id=payment_id, amount_paise=amount, reason=reason, request_key=key or f"k-{new_id()}"
    )


async def refund_and_process(harness: SubscriptionHarness, payment: PaymentRecord, amount: int | None) -> RefundRecord:
    refund = await harness.refunds.create(command(payment.id, amount))
    assert refund.razorpay_refund_id is not None
    await harness.settle_refund(refund.razorpay_refund_id, RefundOutcome.PROCESSED)
    await harness.emit_refund(WebhookEventName.REFUND_PROCESSED, refund.razorpay_refund_id)
    return harness.base.billing.refunds[refund.id]


async def test_a_partial_refund_is_recorded_pending_then_processed_with_a_proportional_clawback(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    payment = await captured_pack_payment(harness)
    half = PACK_PRICE // 2

    refund = await harness.refunds.create(command(payment.id, half, "Duplicate purchase"))

    assert refund.status is RefundStatus.PENDING
    assert (refund.amount_paise, refund.reason, refund.initiated_by) == (half, "Duplicate purchase", ADMIN_ID)
    assert refund.razorpay_refund_id is not None
    remote = await harness.base.razorpay.fetch_refund(refund.razorpay_refund_id)
    assert remote.notes == {"refundId": str(refund.id), "paymentId": str(payment.id)}
    assert (remote.amount, remote.receipt, remote.payment_id) == (half, str(refund.id), payment.razorpay_payment_id)
    assert harness.base.billing.payments[payment.id].refunded_paise == 0
    assert harness.base.balance() == PACK_CREDITS
    created = await harness.emit_refund(WebhookEventName.REFUND_CREATED, refund.razorpay_refund_id)
    assert created.result.state is ProcessingState.PROCESSED
    assert harness.base.billing.refunds[refund.id].status is RefundStatus.PENDING

    await harness.settle_refund(refund.razorpay_refund_id, RefundOutcome.PROCESSED)
    delivered = await harness.emit_refund(WebhookEventName.REFUND_PROCESSED, refund.razorpay_refund_id)

    assert delivered.result.state is ProcessingState.PROCESSED
    settled = harness.base.billing.refunds[refund.id]
    assert settled.status is RefundStatus.PROCESSED
    assert settled.processed_at == harness.base.clock.now()
    assert settled.credits_clawed_back == 50
    stored = harness.base.billing.payments[payment.id]
    assert (stored.status, stored.refunded_paise) == (PaymentRecordStatus.PARTIALLY_REFUNDED, half)
    assert harness.base.balance() == PACK_CREDITS - 50
    assert harness.ledger_keys()[-1] == f"refund:{refund.id}"
    assert harness.base.credits_store.ledger[-1].reason == "refund_clawback"
    notice = harness.base.world.notices[-1]
    assert notice.template == "refund_processed"
    assert notice.context["credits_recovered"] == "50"
    assert notice.context["reference"] == str(refund.id)
    assert {"billing.refund.requested", "billing.refund.processed"} <= set(harness.base.audit_actions())


async def test_a_refund_only_takes_back_credits_that_are_still_unspent(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    payment = await captured_pack_payment(harness)
    await spend(harness, 80)

    refund = await refund_and_process(harness, payment, PACK_PRICE // 2)

    assert refund.credits_clawed_back == 20
    assert harness.base.balance() == 0
    assert harness.base.billing.payments[payment.id].refunded_paise == PACK_PRICE // 2


async def test_spending_a_little_leaves_the_proportional_share_untouched(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    payment = await captured_pack_payment(harness)
    await spend(harness, 20)

    refund = await refund_and_process(harness, payment, PACK_PRICE // 4 + 1)

    assert refund.credits_clawed_back == 26
    assert harness.base.balance() == PACK_CREDITS - 20 - 26


async def test_refunding_a_fully_spent_lot_claws_back_nothing_and_writes_no_ledger_row(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    payment = await captured_pack_payment(harness)
    await spend(harness, PACK_CREDITS)
    ledger_before = len(harness.base.credits_store.ledger)

    refund = await refund_and_process(harness, payment, None)

    assert refund.status is RefundStatus.PROCESSED
    assert refund.credits_clawed_back == 0
    assert len(harness.base.credits_store.ledger) == ledger_before
    stored = harness.base.billing.payments[payment.id]
    assert (stored.status, stored.refunded_paise) == (PaymentRecordStatus.REFUNDED, PACK_PRICE)


async def test_a_duplicate_processed_event_changes_nothing(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    payment = await captured_pack_payment(harness)
    refund = await refund_and_process(harness, payment, PACK_PRICE // 2)
    balance = harness.base.balance()
    ledger = len(harness.base.credits_store.ledger)
    notices = len(harness.base.world.notices)
    assert refund.razorpay_refund_id is not None

    again = await harness.emit_refund(WebhookEventName.REFUND_PROCESSED, refund.razorpay_refund_id)
    async with harness.base.world.transaction() as session:
        repeated = await harness.refund_settlement.apply_processed(session, refund.id)

    assert again.result.state is ProcessingState.PROCESSED
    assert repeated is not None
    assert repeated.credits_clawed_back == refund.credits_clawed_back
    assert harness.base.balance() == balance
    assert len(harness.base.credits_store.ledger) == ledger
    assert len(harness.base.world.notices) == notices
    assert harness.base.billing.payments[payment.id].refunded_paise == PACK_PRICE // 2


async def test_a_failed_refund_is_recorded_alerted_and_frees_the_amount(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    payment = await captured_pack_payment(harness)
    refund = await harness.refunds.create(command(payment.id, None))
    assert refund.razorpay_refund_id is not None
    await harness.settle_refund(refund.razorpay_refund_id, RefundOutcome.FAILED)

    delivered = await harness.emit_refund(WebhookEventName.REFUND_FAILED, refund.razorpay_refund_id)

    assert delivered.result.state is ProcessingState.PROCESSED
    failed = harness.base.billing.refunds[refund.id]
    assert failed.status is RefundStatus.FAILED
    assert failed.failure_reason
    assert failed.processed_at is None
    assert harness.base.billing.payments[payment.id].refunded_paise == 0
    assert harness.base.balance() == PACK_CREDITS
    assert "billing.refund_failed" in [code for code, _ in harness.base.world.alerts]
    assert "billing.refund.failed" in harness.base.audit_actions()
    retry = await harness.refunds.create(command(payment.id, None))
    assert retry.amount_paise == PACK_PRICE


async def test_two_partial_refunds_that_together_exceed_the_payment_are_refused(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    payment = await captured_pack_payment(harness)
    await harness.refunds.create(command(payment.id, 15_000))

    with pytest.raises(RefundExceedsRefundableError) as raised:
        await harness.refunds.create(command(payment.id, 5_000))

    assert raised.value.extensions == {"refundablePaise": PACK_PRICE - 15_000}
    assert raised.value.status_code == 422
    last = await harness.refunds.create(command(payment.id, PACK_PRICE - 15_000))
    assert last.amount_paise == 4_900
    with pytest.raises(RefundExceedsRefundableError) as exhausted:
        await harness.refunds.create(command(payment.id, 1))
    assert exhausted.value.extensions == {"refundablePaise": 0}
    assert len(harness.base.billing.refunds) == 2


async def test_processed_and_pending_refunds_both_count_against_the_payment(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    payment = await captured_pack_payment(harness)
    await refund_and_process(harness, payment, 10_000)
    await harness.refunds.create(command(payment.id, 5_000))

    with pytest.raises(RefundExceedsRefundableError) as raised:
        await harness.refunds.create(command(payment.id, 5_000))

    assert raised.value.extensions == {"refundablePaise": PACK_PRICE - 15_000}


@pytest.mark.parametrize("amount", [0, -1, PACK_PRICE + 1])
async def test_out_of_range_amounts_are_refused_before_anything_is_stored(
    subscription_harness: SubscriptionHarness, amount: int
) -> None:
    harness = subscription_harness
    payment = await captured_pack_payment(harness)

    with pytest.raises(RefundExceedsRefundableError):
        await harness.refunds.create(command(payment.id, amount))

    assert not harness.base.billing.refunds
    assert not await harness.base.razorpay.list_payment_refunds(payment.razorpay_payment_id)


async def test_only_captured_payments_can_be_refunded(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    payment = await captured_pack_payment(harness)

    with pytest.raises(PaymentNotFoundError):
        await harness.refunds.create(command(new_id(), None))
    for status in (PaymentRecordStatus.REFUNDED, PaymentRecordStatus.FAILED, PaymentRecordStatus.AUTHORIZED):
        harness.base.billing.payments[payment.id] = replace(payment, status=status)
        with pytest.raises(PaymentNotRefundableError):
            await harness.refunds.create(command(payment.id, None))

    assert not harness.base.billing.refunds


async def test_a_timeout_after_the_remote_refund_is_recovered_without_a_second_refund(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    payment = await captured_pack_payment(harness)
    await harness.base.razorpay_store.add_fault(FaultOperation.CREATE_REFUND, FaultKind.TIMEOUT_AFTER_CREATE, 1)

    refund = await harness.refunds.create(command(payment.id, 10_000))

    assert refund.razorpay_refund_id is not None
    remote = await harness.base.razorpay.list_payment_refunds(payment.razorpay_payment_id)
    assert [item.id for item in remote] == [refund.razorpay_refund_id]
    assert len(harness.base.billing.refunds) == 1


async def test_a_timeout_before_the_remote_refund_never_resends_and_leaves_the_refund_pending(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    payment = await captured_pack_payment(harness)
    await harness.base.razorpay_store.add_fault(FaultOperation.CREATE_REFUND, FaultKind.TIMEOUT_BEFORE_CREATE, 1)

    with pytest.raises(PaymentProviderUnavailableError):
        await harness.refunds.create(command(payment.id, 10_000))

    [pending] = harness.base.billing.refunds.values()
    assert (pending.status, pending.razorpay_refund_id) == (RefundStatus.PENDING, None)
    assert not await harness.base.razorpay.list_payment_refunds(payment.razorpay_payment_id)
    assert [code for code, _ in harness.base.world.alerts] == ["billing.refund_unconfirmed"]
    with pytest.raises(RefundExceedsRefundableError) as raised:
        await harness.refunds.create(command(payment.id, PACK_PRICE))
    assert raised.value.extensions == {"refundablePaise": PACK_PRICE - 10_000}


async def test_a_failed_lookup_after_an_ambiguous_error_is_reported_and_leaves_the_refund_pending(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    payment = await captured_pack_payment(harness)
    await harness.base.razorpay_store.add_fault(FaultOperation.CREATE_REFUND, FaultKind.TIMEOUT_AFTER_CREATE, 1)
    await harness.base.razorpay_store.add_fault(FaultOperation.LIST_PAYMENT_REFUNDS, FaultKind.SERVER_ERROR, 1)

    with pytest.raises(PaymentProviderUnavailableError):
        await harness.refunds.create(command(payment.id, 10_000))

    [pending] = harness.base.billing.refunds.values()
    assert pending.status is RefundStatus.PENDING
    assert [code for code, _ in harness.base.world.alerts] == ["billing.refund_unconfirmed"]
    [remote] = await harness.base.razorpay.list_payment_refunds(payment.razorpay_payment_id)
    created = await harness.emit_refund(WebhookEventName.REFUND_CREATED, remote.id)
    assert created.result.state is ProcessingState.PROCESSED
    assert harness.base.billing.refunds[pending.id].razorpay_refund_id == remote.id


async def test_a_definite_rejection_marks_the_refund_failed_and_alerts(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    payment = await captured_pack_payment(harness)
    entity = await harness.stored(EntityKind.PAYMENT, payment.razorpay_payment_id)
    entity["status"] = "created"
    await harness.base.razorpay_store.put(EntityKind.PAYMENT, payment.razorpay_payment_id, entity)

    with pytest.raises(RefundRejectedError):
        await harness.refunds.create(command(payment.id, 10_000))

    [refund] = harness.base.billing.refunds.values()
    assert refund.status is RefundStatus.FAILED
    assert refund.failure_reason
    assert "billing.refund_rejected" in [code for code, _ in harness.base.world.alerts]
    assert "billing.refund.rejected" in harness.base.audit_actions()
    assert harness.base.billing.payments[payment.id].refunded_paise == 0


async def test_a_refund_the_provider_already_processed_is_settled_right_away(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    payment = await captured_pack_payment(harness)
    harness.base.razorpay.refund_initial_status = RemoteRefundStatus.PROCESSED

    refund = await harness.refunds.create(command(payment.id, PACK_PRICE // 2))

    assert refund.status is RefundStatus.PROCESSED
    assert refund.credits_clawed_back == 50
    assert harness.base.billing.payments[payment.id].status is PaymentRecordStatus.PARTIALLY_REFUNDED
    assert harness.base.balance() == 50


async def test_a_refund_the_provider_already_failed_is_recorded_failed(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    payment = await captured_pack_payment(harness)
    harness.base.razorpay.refund_initial_status = RemoteRefundStatus.FAILED

    refund = await harness.refunds.create(command(payment.id, 1_000))

    assert refund.status is RefundStatus.FAILED
    assert harness.base.balance() == PACK_CREDITS


async def test_a_refund_event_found_only_through_the_notes_links_the_provider_id(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    payment = await captured_pack_payment(harness)
    refund = await harness.refunds.create(command(payment.id, 10_000))
    assert refund.razorpay_refund_id is not None
    harness.base.billing.refunds[refund.id] = replace(refund, razorpay_refund_id=None)
    await harness.settle_refund(refund.razorpay_refund_id, RefundOutcome.PROCESSED)

    delivered = await harness.emit_refund(WebhookEventName.REFUND_PROCESSED, refund.razorpay_refund_id)

    assert delivered.result.state is ProcessingState.PROCESSED
    settled = harness.base.billing.refunds[refund.id]
    assert settled.razorpay_refund_id == refund.razorpay_refund_id
    assert settled.status is RefundStatus.PROCESSED


async def test_a_refund_nobody_here_asked_for_is_ignored_and_alerted(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    payment = await captured_pack_payment(harness)
    outside = await harness.base.razorpay.create_refund(payment.razorpay_payment_id, amount=5_000)

    delivered = await harness.emit_refund(WebhookEventName.REFUND_PROCESSED, outside.id)

    assert delivered.ignored_reason == "unknown_entity"
    assert harness.base.billing.payments[payment.id].refunded_paise == 0
    assert "billing.unknown_refund" in [code for code, _ in harness.base.world.alerts]


async def test_a_refund_event_for_a_different_payment_is_not_applied(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    payment = await captured_pack_payment(harness)
    other = await captured_pack_payment(harness)
    refund = await harness.refunds.create(command(payment.id, 10_000))
    foreign = await harness.base.razorpay.create_refund(
        other.razorpay_payment_id, amount=5_000, notes={"refundId": str(refund.id)}
    )
    harness.base.billing.refunds[refund.id] = replace(refund, razorpay_refund_id=None)

    delivered = await harness.emit_refund(WebhookEventName.REFUND_PROCESSED, foreign.id)

    assert delivered.ignored_reason == "unknown_entity"
    assert harness.base.billing.refunds[refund.id].status is RefundStatus.PENDING
    assert "billing.refund_payment_mismatch" in [code for code, _ in harness.base.world.alerts]


async def test_a_payment_that_granted_no_credits_claws_back_nothing(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    payment = await captured_pack_payment(harness)
    harness.base.billing.payments[payment.id] = replace(payment, credits_granted=0)
    ledger = len(harness.base.credits_store.ledger)

    refund = await refund_and_process(harness, payment, 10_000)

    assert refund.credits_clawed_back == 0
    assert len(harness.base.credits_store.ledger) == ledger


async def test_a_payment_without_a_lot_claws_back_nothing(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    payment = await captured_pack_payment(harness)
    harness.base.credits_store.lots.clear()

    refund = await refund_and_process(harness, payment, 10_000)

    assert refund.credits_clawed_back == 0
    assert refund.status is RefundStatus.PROCESSED


async def test_rounding_across_partial_refunds_never_takes_more_than_was_granted(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    payment = await captured_pack_payment(harness)
    third = PACK_PRICE // 3

    first = await refund_and_process(harness, payment, third)
    second = await refund_and_process(harness, payment, third)
    third_refund = await refund_and_process(harness, payment, PACK_PRICE - 2 * third)

    taken = first.credits_clawed_back + second.credits_clawed_back + third_refund.credits_clawed_back
    assert taken == PACK_CREDITS
    assert harness.base.balance() == 0
    assert harness.base.billing.payments[payment.id].status is PaymentRecordStatus.REFUNDED


async def test_refunding_a_subscription_payment_takes_back_its_credits_but_keeps_the_subscription(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    await harness.activate(checkout)
    [payment] = harness.base.billing.payments.values()

    refund = await refund_and_process(harness, payment, PLAN_PRICE // 2)

    assert refund.credits_clawed_back == PLAN_CREDITS // 2
    assert harness.base.balance() == PLAN_CREDITS - PLAN_CREDITS // 2
    assert harness.local(checkout).status is SubscriptionStatus.ACTIVE
    assert harness.local(checkout).cancel_at_period_end is False
