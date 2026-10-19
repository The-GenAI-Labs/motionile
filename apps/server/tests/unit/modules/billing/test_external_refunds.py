import pytest
from tests.unit.modules.billing.conftest import PACK_CREDITS, PACK_PRICE, BillingHarness
from tests.unit.modules.billing.subscription_support import PLAN_CREDITS, PLAN_PRICE, SubscriptionHarness
from tests.unit.modules.billing.test_refunds import command

from motionile.core.ids import new_id
from motionile.modules.billing.exceptions import RefundExceedsRefundableError
from motionile.modules.billing.razorpay.fake_events import WebhookEventName
from motionile.modules.billing.razorpay.fake_simulator import RefundOutcome, SubscriptionEvent
from motionile.modules.billing.razorpay.fake_store import EntityKind
from motionile.modules.billing.records import NewRefund, PaymentRecord
from motionile.modules.billing.services.decisions import SettlementOutcome, SettlementSource
from motionile.modules.billing.services.webhook_processor import ProcessingState
from motionile.modules.billing.states import OrderStatus, PaymentRecordStatus, RefundStatus


@pytest.fixture
def subscription_harness(billing_harness: BillingHarness) -> SubscriptionHarness:
    return SubscriptionHarness(billing_harness)


async def settle_refunded_pack(harness: SubscriptionHarness, refunded: int) -> PaymentRecord:
    base = harness.base
    order = await base.open_order()
    payment = await base.pay(order)
    entity = await harness.stored(EntityKind.PAYMENT, payment.id)
    entity["amount_refunded"] = refunded
    entity["status"] = "refunded" if refunded >= PACK_PRICE else "partially_refunded"
    await base.razorpay_store.put(EntityKind.PAYMENT, payment.id, entity)
    remote = await base.razorpay.fetch_payment(payment.id)
    async with base.world.transaction() as session:
        result = await base.settlement.settle(session, remote, SettlementSource.WEBHOOK)
    assert result.outcome is SettlementOutcome.SETTLED
    assert result.payment_id is not None
    return base.billing.payments[result.payment_id]


async def external_refund(
    harness: SubscriptionHarness, payment: PaymentRecord, amount: int, outcome: RefundOutcome | None = None
) -> str:
    remote = await harness.base.razorpay.create_refund(payment.razorpay_payment_id, amount=amount)
    if outcome is not None:
        await harness.settle_refund(remote.id, outcome)
    return remote.id


async def capture_pack(harness: SubscriptionHarness) -> PaymentRecord:
    return await settle_refunded_pack(harness, 0)


async def test_a_payment_already_partly_refunded_when_settled_gets_proportional_credits(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness

    payment = await settle_refunded_pack(harness, PACK_PRICE // 2)

    assert (payment.status, payment.refunded_paise) == (PaymentRecordStatus.PARTIALLY_REFUNDED, PACK_PRICE // 2)
    assert payment.credits_granted == PACK_CREDITS - 50
    assert harness.base.balance() == PACK_CREDITS - 50
    [entry] = harness.base.credits_store.ledger
    assert entry.metadata["refundedPaise"] == PACK_PRICE // 2
    assert entry.metadata["orderCredits"] == PACK_CREDITS
    [receipt] = harness.base.world.receipts
    assert receipt.credits == PACK_CREDITS - 50


async def test_a_payment_already_fully_refunded_when_settled_grants_nothing_but_pays_the_order(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness

    payment = await settle_refunded_pack(harness, PACK_PRICE)

    assert (payment.status, payment.refunded_paise, payment.credits_granted) == (
        PaymentRecordStatus.REFUNDED,
        PACK_PRICE,
        0,
    )
    assert harness.base.balance() == 0
    assert not harness.base.credits_store.ledger
    assert not harness.base.world.receipts
    [order] = harness.base.billing.orders.values()
    assert order.status is OrderStatus.PAID
    assert "billing.order.paid" in harness.base.audit_actions()


async def test_a_subscription_charge_already_partly_refunded_gets_proportional_credits(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    authorization, _ = await harness.authorize(checkout.razorpay_subscription_id)
    payment = await harness.stored(EntityKind.PAYMENT, authorization.payment["id"])
    payment["amount_refunded"] = PLAN_PRICE // 2
    payment["status"] = "partially_refunded"
    await harness.base.razorpay_store.put(EntityKind.PAYMENT, payment["id"], payment)
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.ACTIVATED)

    await harness.emit(
        WebhookEventName.SUBSCRIPTION_CHARGED, checkout.razorpay_subscription_id, payment_id=payment["id"]
    )

    [recorded] = harness.base.billing.payments.values()
    assert (recorded.status, recorded.refunded_paise) == (PaymentRecordStatus.PARTIALLY_REFUNDED, PLAN_PRICE // 2)
    assert recorded.credits_granted == PLAN_CREDITS - PLAN_CREDITS // 2
    assert harness.base.balance() == PLAN_CREDITS - PLAN_CREDITS // 2


async def test_a_dashboard_refund_on_a_known_payment_is_adopted_and_claws_back_credits(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    payment = await capture_pack(harness)
    remote_id = await external_refund(harness, payment, PACK_PRICE // 2, RefundOutcome.PROCESSED)

    delivered = await harness.emit_refund(WebhookEventName.REFUND_PROCESSED, remote_id)

    assert delivered.result.state is ProcessingState.PROCESSED
    [refund] = harness.base.billing.refunds.values()
    assert (refund.status, refund.initiated_by, refund.reason) == (RefundStatus.PROCESSED, None, "external_refund")
    assert (refund.idempotency_key, refund.razorpay_refund_id) == (f"external:{remote_id}", remote_id)
    assert refund.credits_clawed_back == 50
    stored = harness.base.billing.payments[payment.id]
    assert (stored.status, stored.refunded_paise) == (PaymentRecordStatus.PARTIALLY_REFUNDED, PACK_PRICE // 2)
    assert harness.base.balance() == PACK_CREDITS - 50
    assert harness.base.world.notices[-1].template == "refund_processed"
    assert {"billing.refund.adopted", "billing.refund.processed"} <= set(harness.base.audit_actions())
    assert "billing.unknown_refund" not in [code for code, _ in harness.base.world.alerts]


async def test_adopting_the_same_dashboard_refund_twice_changes_nothing(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    payment = await capture_pack(harness)
    remote_id = await external_refund(harness, payment, PACK_PRICE // 2, RefundOutcome.PROCESSED)
    await harness.emit_refund(WebhookEventName.REFUND_CREATED, remote_id)
    await harness.emit_refund(WebhookEventName.REFUND_PROCESSED, remote_id)
    balance = harness.base.balance()

    await harness.emit_refund(WebhookEventName.REFUND_PROCESSED, remote_id)
    await harness.emit_refund(WebhookEventName.REFUND_CREATED, remote_id)

    assert len(harness.base.billing.refunds) == 1
    assert harness.base.billing.payments[payment.id].refunded_paise == PACK_PRICE // 2
    assert harness.base.balance() == balance
    assert len(harness.base.world.notices) == 1


async def test_a_pending_dashboard_refund_is_adopted_pending_and_counts_against_the_payment(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    payment = await capture_pack(harness)
    remote_id = await external_refund(harness, payment, 15_000)

    await harness.emit_refund(WebhookEventName.REFUND_CREATED, remote_id)

    [refund] = harness.base.billing.refunds.values()
    assert refund.status is RefundStatus.PENDING
    with pytest.raises(RefundExceedsRefundableError) as raised:
        await harness.refunds.create(command(payment.id, 5_000))
    assert raised.value.extensions == {"refundablePaise": PACK_PRICE - 15_000}


async def test_a_failed_dashboard_refund_is_recorded_failed_and_alerted(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    payment = await capture_pack(harness)
    remote_id = await external_refund(harness, payment, 5_000, RefundOutcome.FAILED)

    delivered = await harness.emit_refund(WebhookEventName.REFUND_FAILED, remote_id)

    assert delivered.result.state is ProcessingState.PROCESSED
    [refund] = harness.base.billing.refunds.values()
    assert refund.status is RefundStatus.FAILED
    assert "billing.refund_failed" in [code for code, _ in harness.base.world.alerts]
    assert harness.base.billing.payments[payment.id].refunded_paise == 0


async def test_a_dashboard_refund_on_an_unknown_payment_is_still_ignored(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    payment = await capture_pack(harness)
    remote_id = await external_refund(harness, payment, 5_000, RefundOutcome.PROCESSED)
    del harness.base.billing.payments[payment.id]

    delivered = await harness.emit_refund(WebhookEventName.REFUND_PROCESSED, remote_id)

    assert delivered.ignored_reason == "unknown_entity"
    assert not harness.base.billing.refunds
    assert "billing.unknown_refund" in [code for code, _ in harness.base.world.alerts]


async def test_a_dashboard_refund_that_would_exceed_the_payment_is_not_adopted(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    payment = await capture_pack(harness)
    await harness.base.billing.insert_refund(NewRefund(new_id(), payment.id, 15_000, "local only", None, "k-local"))
    remote_id = await external_refund(harness, payment, 10_000, RefundOutcome.PROCESSED)

    delivered = await harness.emit_refund(WebhookEventName.REFUND_PROCESSED, remote_id)

    assert delivered.ignored_reason == "unknown_entity"
    assert len(harness.base.billing.refunds) == 1
    assert harness.base.billing.payments[payment.id].refunded_paise == 0
    assert "billing.external_refund_exceeds_payment" in [code for code, _ in harness.base.world.alerts]


async def test_a_refund_already_counted_when_the_payment_was_settled_is_not_counted_twice(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    payment = await settle_refunded_pack(harness, PACK_PRICE // 2)
    remote_id = await external_refund(harness, payment, PACK_PRICE // 2, RefundOutcome.PROCESSED)

    await harness.emit_refund(WebhookEventName.REFUND_PROCESSED, remote_id)

    stored = harness.base.billing.payments[payment.id]
    assert stored.refunded_paise == PACK_PRICE // 2
    [adopted] = harness.base.billing.refunds.values()
    assert (adopted.status, adopted.credits_clawed_back) == (RefundStatus.PROCESSED, 0)
    assert harness.base.balance() == PACK_CREDITS - 50


async def test_the_rest_of_a_payment_refunded_before_settlement_claws_back_every_remaining_credit(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    payment = await settle_refunded_pack(harness, PACK_PRICE // 2)
    rest = PACK_PRICE - PACK_PRICE // 2

    refund = await harness.refunds.create(command(payment.id, rest))
    assert refund.razorpay_refund_id is not None
    await harness.settle_refund(refund.razorpay_refund_id, RefundOutcome.PROCESSED)
    await harness.emit_refund(WebhookEventName.REFUND_PROCESSED, refund.razorpay_refund_id)

    settled = harness.base.billing.refunds[refund.id]
    assert settled.credits_clawed_back == PACK_CREDITS - 50
    assert harness.base.balance() == 0
    assert harness.base.billing.payments[payment.id].status is PaymentRecordStatus.REFUNDED
