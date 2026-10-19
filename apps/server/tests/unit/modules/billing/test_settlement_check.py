from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import orjson
import pytest
from tests.fakes.storage import InMemoryStorage
from tests.unit.modules.billing.conftest import PACK_PRICE, BillingHarness
from tests.unit.modules.billing.subscription_support import SubscriptionHarness

from motionile.core.ids import new_id
from motionile.modules.billing.exceptions import SettlementWindowTooLargeError
from motionile.modules.billing.razorpay.exceptions import RazorpayServerError
from motionile.modules.billing.razorpay.fake_entities import PaymentSpec, epoch, new_entity_id, payment_entity
from motionile.modules.billing.razorpay.fake_store import EntityKind, FaultKind, FaultOperation
from motionile.modules.billing.razorpay.models import RazorpayPayment
from motionile.modules.billing.records import LocalPayment, NewPayment, NewRefund, PaymentRecord
from motionile.modules.billing.services import settlement_check as settlement_module
from motionile.modules.billing.services import settlement_diff
from motionile.modules.billing.services.settlement_check import (
    SettlementCheck,
    SettlementCheckDependencies,
    previous_day,
    window_for,
)
from motionile.modules.billing.services.settlement_diff import (
    DifferingField,
    DiffTally,
    DiscrepancyKind,
    compare_payment,
    extra_payment,
)
from motionile.modules.billing.states import PaymentRecordStatus, RunStatus

DAY = date(2026, 10, 17)
NOON = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
CHECK_TIME = datetime(2026, 10, 18, 4, 0, tzinfo=UTC)
REPORT_KEY = "billing/reconciliation/settlement/2026-10-17.json"


@pytest.fixture
def subscription_harness(billing_harness: BillingHarness) -> SubscriptionHarness:
    return SubscriptionHarness(billing_harness)


def checker_for(harness: SubscriptionHarness, storage: InMemoryStorage) -> SettlementCheck:
    base = harness.base
    return SettlementCheck(
        SettlementCheckDependencies(base.world.transaction, base.razorpay, storage, base.clock, base.settings),
        store_factory=base.billing,
        alert=base.world.alert,
    )


async def remote_payment(
    harness: SubscriptionHarness, *, amount: int = PACK_PRICE, status: str = "captured", currency: str = "INR"
) -> str:
    store = harness.base.razorpay_store
    payment_id = await new_entity_id(store, "pay")
    entity = payment_entity(
        payment_id,
        harness.base.clock.now(),
        PaymentSpec(amount=amount, currency=currency, status=status, order_id="order_x"),
    )
    await store.put(EntityKind.PAYMENT, payment_id, entity)
    await store.append("payments", "all", payment_id)
    return payment_id


async def local_payment(
    harness: SubscriptionHarness,
    razorpay_payment_id: str,
    *,
    amount: int = PACK_PRICE,
    status: PaymentRecordStatus = PaymentRecordStatus.CAPTURED,
    currency: str = "INR",
) -> PaymentRecord:
    return await harness.base.billing.insert_payment(
        NewPayment(
            id=new_id(),
            order_id=new_id(),
            user_id=harness.base.user_id,
            razorpay_payment_id=razorpay_payment_id,
            amount_paise=amount,
            currency=currency,
            status=status,
        )
    )


async def matched_pair(harness: SubscriptionHarness, amount: int = PACK_PRICE) -> tuple[str, PaymentRecord]:
    payment_id = await remote_payment(harness, amount=amount)
    return payment_id, await local_payment(harness, payment_id, amount=amount)


async def report_of(storage: InMemoryStorage) -> dict[str, Any]:
    data = b"".join([chunk async for chunk in storage.get(REPORT_KEY)])
    document: dict[str, Any] = orjson.loads(data)
    return document


def at_noon(harness: SubscriptionHarness) -> None:
    harness.base.clock.set(NOON)


def at_check_time(harness: SubscriptionHarness) -> None:
    harness.base.clock.set(CHECK_TIME)


async def test_a_clean_day_writes_a_report_and_raises_no_alert(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    at_noon(harness)
    await matched_pair(harness)
    await matched_pair(harness, amount=4_900)
    await remote_payment(harness, status="failed")
    storage = InMemoryStorage()
    at_check_time(harness)

    result = await checker_for(harness, storage).run()

    assert result is not None
    assert (result.day, result.report_key, result.mismatches, result.resumed) == (DAY, REPORT_KEY, 0, False)
    assert result.checked == 3
    report = await report_of(storage)
    assert report["date"] == "2026-10-17"
    assert report["counts"] == {"checked": 3, "mismatches": 0, "missing": 0, "extra": 0, "mismatched": 0}
    assert report["mismatches"] == []
    assert report["truncated"] is False
    [run_id] = harness.base.billing.runs
    outcome = harness.base.billing.runs[run_id]
    assert outcome is not None
    assert (outcome.status, outcome.counts.checked, outcome.counts.mismatch) == (RunStatus.COMPLETED, 3, 0)
    assert outcome.report_storage_key == REPORT_KEY
    assert outcome.summary == {"missing": 0, "extra": 0, "mismatched": 0}
    assert harness.base.billing.run_types[run_id] == "settlement"
    assert harness.base.world.alerts == []
    assert storage.objects[REPORT_KEY].content_type == "application/json"


async def test_missing_extra_and_mismatched_payments_are_reported_and_alerted(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    at_noon(harness)
    missing_id = await remote_payment(harness, amount=7_700)
    await matched_pair(harness)
    extra_id = f"pay_{new_id().hex[:14]}"
    await local_payment(harness, extra_id, amount=3_300)
    wrong_amount_id = await remote_payment(harness, amount=9_900)
    await local_payment(harness, wrong_amount_id, amount=9_800)
    storage = InMemoryStorage()
    at_check_time(harness)

    result = await checker_for(harness, storage).run()

    assert result is not None
    assert result.mismatches == 3
    report = await report_of(storage)
    assert report["counts"] == {"checked": 4, "mismatches": 3, "missing": 1, "extra": 1, "mismatched": 1}
    entries = {item["razorpayPaymentId"]: item for item in report["mismatches"]}
    assert entries[missing_id]["kind"] == "missing"
    assert entries[missing_id]["remote"]["amountPaise"] == 7_700
    assert entries[missing_id]["local"] is None
    assert entries[extra_id]["kind"] == "extra"
    assert entries[extra_id]["remote"] is None
    assert entries[extra_id]["local"]["amountPaise"] == 3_300
    assert entries[wrong_amount_id]["kind"] == "mismatched"
    assert entries[wrong_amount_id]["fields"] == ["amount"]
    assert entries[wrong_amount_id]["remote"]["amountPaise"] == 9_900
    assert entries[wrong_amount_id]["local"]["amountPaise"] == 9_800
    [run_id] = harness.base.billing.runs
    outcome = harness.base.billing.runs[run_id]
    assert outcome is not None
    assert outcome.counts.mismatch == 3
    assert outcome.summary == {"missing": 1, "extra": 1, "mismatched": 1}
    [(code, fields)] = harness.base.world.alerts
    assert code == "billing.reconciliation_mismatch"
    assert (fields["missing"], fields["extra"], fields["mismatched"], fields["report_key"]) == (1, 1, 1, REPORT_KEY)


async def test_the_report_carries_no_personal_data(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    at_noon(harness)
    await remote_payment(harness)
    storage = InMemoryStorage()
    at_check_time(harness)

    await checker_for(harness, storage).run()

    raw = storage.objects[REPORT_KEY].data.decode()
    for personal in ("customer@example.com", "+919999999999", "email", "contact", "notes"):
        assert personal not in raw


async def test_currency_status_and_refund_differences_are_named(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    at_noon(harness)
    currency_id = await remote_payment(harness, currency="USD")
    await local_payment(harness, currency_id)
    status_id = await remote_payment(harness, status="failed")
    await local_payment(harness, status_id)
    refunded_id = await remote_payment(harness)
    await local_payment(harness, refunded_id)
    entity = await harness.stored(EntityKind.PAYMENT, refunded_id)
    entity["amount_refunded"] = 5_000
    await harness.base.razorpay_store.put(EntityKind.PAYMENT, refunded_id, entity)
    storage = InMemoryStorage()
    at_check_time(harness)

    await checker_for(harness, storage).run()

    report = await report_of(storage)
    fields = {item["razorpayPaymentId"]: item["fields"] for item in report["mismatches"]}
    assert fields[currency_id] == ["currency"]
    assert fields[status_id] == ["status"]
    assert fields[refunded_id] == ["refunded"]


async def test_refunds_in_flight_or_processed_do_not_look_like_mismatches(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    at_noon(harness)
    pending_id, pending_payment = await matched_pair(harness)
    processed_id, processed_payment = await matched_pair(harness)
    await harness.base.razorpay.create_refund(pending_id, amount=5_000)
    await harness.base.billing.insert_refund(NewRefund(new_id(), pending_payment.id, 5_000, "test", None, "k-pending"))
    await harness.base.razorpay.create_refund(processed_id, amount=PACK_PRICE)
    harness.base.billing.payments[processed_payment.id] = replace(
        processed_payment, status=PaymentRecordStatus.REFUNDED, refunded_paise=PACK_PRICE
    )
    storage = InMemoryStorage()
    at_check_time(harness)

    result = await checker_for(harness, storage).run()

    assert result is not None
    assert (result.checked, result.mismatches) == (2, 0)
    assert harness.base.world.alerts == []


async def test_a_payment_recorded_after_midnight_is_not_reported_as_extra(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    harness.base.clock.set(datetime(2026, 10, 17, 23, 59, 58, tzinfo=UTC))
    payment_id = await remote_payment(harness)
    harness.base.clock.set(datetime(2026, 10, 18, 0, 0, 5, tzinfo=UTC))
    await local_payment(harness, payment_id)
    storage = InMemoryStorage()
    at_check_time(harness)
    checker = checker_for(harness, storage)

    previous = await checker.run(DAY)
    following = await checker.run(date(2026, 10, 18))

    assert previous is not None
    assert following is not None
    assert (previous.mismatches, following.mismatches) == (0, 0)
    assert harness.base.world.alerts == []


async def test_a_day_is_checked_once(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    at_noon(harness)
    await matched_pair(harness)
    storage = InMemoryStorage()
    at_check_time(harness)
    checker = checker_for(harness, storage)

    first = await checker.run()
    second = await checker.run()

    assert first is not None
    assert second is None
    assert len(harness.base.billing.runs) == 1
    assert list(storage.objects) == [REPORT_KEY]


async def test_a_failed_run_is_resumed_by_the_next_attempt(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    at_noon(harness)
    await matched_pair(harness)
    storage = InMemoryStorage()
    at_check_time(harness)
    checker = checker_for(harness, storage)
    await harness.base.razorpay_store.add_fault(FaultOperation.LIST_PAYMENTS, FaultKind.SERVER_ERROR, 1)

    with pytest.raises(RazorpayServerError):
        await checker.run()

    [run_id] = harness.base.billing.runs
    failed = harness.base.billing.runs[run_id]
    assert failed is not None
    assert failed.status is RunStatus.FAILED
    assert failed.error
    assert not storage.objects

    resumed = await checker.run()

    assert resumed is not None
    assert resumed.run_id == run_id
    assert resumed.resumed is True
    outcome = harness.base.billing.runs[run_id]
    assert outcome is not None
    assert outcome.status is RunStatus.COMPLETED
    assert REPORT_KEY in storage.objects


async def test_a_run_that_looks_abandoned_is_taken_over(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    at_noon(harness)
    await matched_pair(harness)
    storage = InMemoryStorage()
    at_check_time(harness)
    start = harness.base.clock.now()
    claim = await harness.base.billing.claim_settlement_run(
        window_for(DAY).start, window_for(DAY).end, start, start - timedelta(hours=1)
    )
    assert claim is not None
    checker = checker_for(harness, storage)

    assert await checker.run() is None
    harness.base.clock.advance(timedelta(hours=2))
    taken = await checker.run()

    assert taken is not None
    assert (taken.run_id, taken.resumed) == (claim.run_id, True)


async def test_every_page_of_payments_is_compared(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    at_noon(harness)
    for _ in range(105):
        await matched_pair(harness)
    storage = InMemoryStorage()
    at_check_time(harness)

    result = await checker_for(harness, storage).run()

    assert result is not None
    assert (result.checked, result.mismatches) == (105, 0)


async def test_a_window_with_too_many_pages_fails_the_run(
    subscription_harness: SubscriptionHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = subscription_harness
    at_noon(harness)
    for _ in range(100):
        await matched_pair(harness)
    storage = InMemoryStorage()
    at_check_time(harness)
    monkeypatch.setattr(settlement_module, "MAX_REMOTE_PAGES", 1)

    with pytest.raises(SettlementWindowTooLargeError):
        await checker_for(harness, storage).run()

    [run_id] = harness.base.billing.runs
    outcome = harness.base.billing.runs[run_id]
    assert outcome is not None
    assert outcome.status is RunStatus.FAILED


async def test_the_report_lists_only_the_first_mismatches_but_counts_all_of_them(
    subscription_harness: SubscriptionHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = subscription_harness
    at_noon(harness)
    for _ in range(5):
        await remote_payment(harness)
    storage = InMemoryStorage()
    at_check_time(harness)
    monkeypatch.setattr(settlement_diff, "REPORT_MISMATCH_LIMIT", 3)

    result = await checker_for(harness, storage).run()

    assert result is not None
    assert result.mismatches == 5
    report = await report_of(storage)
    assert len(report["mismatches"]) == 3
    assert report["truncated"] is True
    assert report["counts"]["mismatches"] == 5


def test_the_previous_utc_day_is_checked() -> None:
    assert previous_day(datetime(2026, 10, 18, 4, 0, tzinfo=UTC)) == date(2026, 10, 17)
    assert previous_day(datetime(2026, 1, 1, 0, 0, tzinfo=UTC)) == date(2025, 12, 31)
    window = window_for(DAY)
    assert (window.start, window.end) == (NOON.replace(hour=0), NOON.replace(hour=0) + timedelta(days=1))


def remote_model(**values: object) -> RazorpayPayment:
    document: dict[str, object] = {
        "id": "pay_1",
        "amount": PACK_PRICE,
        "currency": "INR",
        "status": "captured",
        "captured": True,
        "amount_refunded": 0,
        "created_at": epoch(NOON),
        **values,
    }
    return RazorpayPayment.model_validate(document)


def local_model(
    status: PaymentRecordStatus = PaymentRecordStatus.CAPTURED, *, refunded: int = 0, pending: int = 0, **values: object
) -> LocalPayment:
    payment = PaymentRecord(
        id=new_id(),
        order_id=None,
        subscription_id=None,
        user_id=new_id(),
        razorpay_payment_id="pay_1",
        amount_paise=PACK_PRICE,
        currency="INR",
        status=status,
        method=None,
        fee_paise=None,
        tax_paise=None,
        credits_granted=0,
        refunded_paise=refunded,
        error_code=None,
        error_description=None,
        captured_at=None,
        created_at=NOON,
    )
    return LocalPayment(replace(payment, **values), pending)


def test_identical_payments_are_not_discrepancies() -> None:
    assert compare_payment(remote_model(), local_model()) is None
    assert compare_payment(remote_model(status="failed", captured=False), None) is None


def test_a_captured_remote_payment_without_a_local_one_is_missing() -> None:
    found = compare_payment(remote_model(), None)

    assert found is not None
    assert found.kind is DiscrepancyKind.MISSING
    assert found.local is None


@pytest.mark.parametrize(
    ("remote", "local", "fields"),
    [
        ({"amount": PACK_PRICE + 1}, local_model(), (DifferingField.AMOUNT,)),
        ({"currency": "USD"}, local_model(), (DifferingField.CURRENCY,)),
        ({"status": "failed", "captured": False}, local_model(), (DifferingField.STATUS,)),
        ({}, local_model(PaymentRecordStatus.AUTHORIZED), (DifferingField.STATUS,)),
        ({"amount_refunded": 100}, local_model(), (DifferingField.REFUNDED,)),
        ({"amount_refunded": 100}, local_model(pending=100), ()),
        (
            {"amount_refunded": 300, "status": "partially_refunded"},
            local_model(PaymentRecordStatus.PARTIALLY_REFUNDED, refunded=200, pending=100),
            (),
        ),
        (
            {"amount": 1, "currency": "USD", "amount_refunded": 5},
            local_model(),
            (DifferingField.AMOUNT, DifferingField.CURRENCY, DifferingField.REFUNDED),
        ),
    ],
)
def test_each_difference_is_named(
    remote: dict[str, object], local: LocalPayment, fields: tuple[DifferingField, ...]
) -> None:
    found = compare_payment(remote_model(**remote), local)

    assert (found.fields if found is not None else ()) == fields


def test_the_tally_counts_everything_and_lists_a_bounded_number(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settlement_diff, "REPORT_MISMATCH_LIMIT", 2)
    tally = DiffTally()

    for _ in range(3):
        tally.examined()
        tally.add(extra_payment(local_model()))
    tally.add(compare_payment(remote_model(), None) or extra_payment(local_model()))

    assert tally.checked == 3
    assert (tally.count(DiscrepancyKind.EXTRA), tally.count(DiscrepancyKind.MISSING)) == (3, 1)
    assert tally.mismatches == 4
    assert len(tally.listed) == 2
    assert tally.truncated is True
    assert tally.summary() == {"missing": 1, "extra": 3, "mismatched": 0}
