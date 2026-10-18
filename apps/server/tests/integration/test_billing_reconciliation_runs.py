import json
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from tests.integration.billing_support import PACK_PRICE, BillingApi

from motionile.core.ids import new_id
from motionile.modules.billing.razorpay.exceptions import RazorpayServerError
from motionile.modules.billing.razorpay.factory import fake_store_for
from motionile.modules.billing.razorpay.fake_store import EntityKind
from motionile.modules.billing.records import NewPayment
from motionile.modules.billing.repository import SqlBillingRepository
from motionile.modules.billing.states import PaymentRecordStatus

REPORT_PREFIX = "billing/reconciliation/settlement"


async def align_payments_with_the_clock(api: BillingApi) -> None:
    async with api.database.transaction() as session:
        await session.execute(text("UPDATE payments SET created_at = :now"), {"now": api.clock.now()})


async def paid_pack(api: BillingApi) -> tuple[str, str]:
    checkout = await api.checkout()
    paid = await api.pay(checkout["razorpayOrderId"])
    response = await api.verify(paid)
    assert response.status_code == 200, response.text
    return checkout["orderId"], paid["razorpay_payment_id"]


def stored_report(api: BillingApi, day: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(api.storage.objects[f"{REPORT_PREFIX}/{day}.json"].data)
    return document


async def test_the_settlement_check_reports_missing_extra_and_mismatched_payments(billing_api: BillingApi) -> None:
    day = billing_api.clock.now().date()
    clean_order, clean_payment = await paid_pack(billing_api)
    _, refunded_payment = await paid_pack(billing_api)
    unrecorded = await billing_api.checkout()
    missing_payment = await billing_api.add_captured_payment(unrecorded["razorpayOrderId"])
    async with billing_api.database.transaction() as session:
        await SqlBillingRepository(session).insert_payment(
            NewPayment(
                id=new_id(),
                order_id=UUID(clean_order),
                user_id=billing_api.primary_id,
                razorpay_payment_id="pay_ghost",
                amount_paise=PACK_PRICE,
                currency="INR",
                status=PaymentRecordStatus.CAPTURED,
            )
        )
    store = fake_store_for(billing_api.resources)
    entity = await store.get(EntityKind.PAYMENT, refunded_payment)
    assert entity is not None
    await store.put(EntityKind.PAYMENT, refunded_payment, {**entity, "amount_refunded": 500})
    await align_payments_with_the_clock(billing_api)

    result = await billing_api.services.settlement_check.run(day)

    assert result is not None
    assert (result.mismatches, result.checked) == (3, 4)
    report = stored_report(billing_api, day.isoformat())
    assert report["counts"] == {"checked": 4, "mismatches": 3, "missing": 1, "extra": 1, "mismatched": 1}
    by_id = {item["razorpayPaymentId"]: item for item in report["mismatches"]}
    assert by_id[missing_payment]["kind"] == "missing"
    assert by_id["pay_ghost"]["kind"] == "extra"
    assert by_id[refunded_payment]["kind"] == "mismatched"
    assert by_id[refunded_payment]["fields"] == ["refunded"]
    assert clean_payment not in by_id
    [run] = await billing_api.run_rows("settlement")
    assert (run.status, run.checked_count, run.mismatch_count) == ("completed", 4, 3)
    assert run.report_storage_key == f"{REPORT_PREFIX}/{day.isoformat()}.json"
    assert run.summary == {"missing": 1, "extra": 1, "mismatched": 1}
    assert run.period_start is not None
    assert run.period_end is not None
    assert (run.period_end - run.period_start).days == 1
    [(_, fields)] = [item for item in billing_api.recorded.alerts if item[0] == "billing.reconciliation_mismatch"]
    assert (fields["missing"], fields["extra"], fields["mismatched"]) == (1, 1, 1)

    again = await billing_api.services.settlement_check.run(day)

    assert again is None
    assert len(await billing_api.run_rows("settlement")) == 1
    assert len(billing_api.storage.objects) == 1


async def test_a_clean_day_raises_no_alert_and_a_failed_check_is_resumed(billing_api: BillingApi) -> None:
    day = billing_api.clock.now().date()
    await paid_pack(billing_api)
    await align_payments_with_the_clock(billing_api)
    await billing_api.arm_fault("list_payments", "server_error")

    with pytest.raises(RazorpayServerError):
        await billing_api.services.settlement_check.run(day)

    [failed] = await billing_api.run_rows("settlement")
    assert failed.status == "failed"
    assert failed.error
    assert failed.report_storage_key is None
    assert not billing_api.storage.objects

    resumed = await billing_api.services.settlement_check.run(day)

    assert resumed is not None
    assert (resumed.run_id, resumed.resumed, resumed.mismatches) == (failed.id, True, 0)
    [done] = await billing_api.run_rows("settlement")
    assert (done.status, done.error, done.checked_count) == ("completed", None, 1)
    assert billing_api.recorded.alert_codes() == []


async def test_dropped_webhooks_leave_a_payment_that_only_the_settlement_check_can_see(billing_api: BillingApi) -> None:
    day = billing_api.clock.now().date()
    code = await billing_api.plan_product()
    started = await billing_api.started_subscription(code)
    remote_id = started["razorpaySubscriptionId"]
    authorized = await billing_api.authorize_subscription(remote_id)
    await billing_api.verify_subscription(authorized)
    await billing_api.transition(remote_id, "activated", emit=False)

    synced = await billing_api.services.subscriptions.sync.run()
    checked = await billing_api.services.settlement_check.run(day)

    assert synced.repaired == 1
    assert (await billing_api.subscription_row(started["subscriptionId"])).status == "active"
    assert await billing_api.payment_rows() == []
    assert await billing_api.wallet_balance(billing_api.primary_id) == 0
    assert checked is not None
    assert checked.mismatches == 1
    report = stored_report(billing_api, day.isoformat())
    [entry] = report["mismatches"]
    assert (entry["kind"], entry["razorpayPaymentId"]) == ("missing", authorized["razorpay_payment_id"])
    assert billing_api.recorded.alert_codes() == ["billing.reconciliation_mismatch"]
