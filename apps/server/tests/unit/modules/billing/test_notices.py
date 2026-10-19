from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.ids import new_id
from motionile.core.resources import Resources
from motionile.modules.billing.services import notices as notices_module
from motionile.modules.billing.services.notices import (
    BillingNotice,
    ChargeSummary,
    NoticeMailer,
    RefundSummary,
    cancellation_notice,
    charge_failed_notice,
    charge_notice,
    ended_notice,
    formatted_date,
    halted_notice,
    refund_notice,
)
from motionile.modules.notifications import Notification
from motionile.modules.notifications.rendering import render_email

USER_ID = new_id()
NEXT = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)
SUMMARY = ChargeSummary(plan_name="Pro", amount_paise=99_900, currency="INR", credit_count=500, next_charge_at=NEXT)


def all_notices() -> list[BillingNotice]:
    return [
        charge_notice(USER_ID, SUMMARY, first=True),
        charge_notice(USER_ID, SUMMARY, first=False),
        charge_failed_notice(USER_ID, "Pro", NEXT),
        halted_notice(USER_ID, "Pro"),
        cancellation_notice(USER_ID, "Pro", NEXT),
        ended_notice(USER_ID, "Pro"),
        refund_notice(USER_ID, RefundSummary(19_900, "INR", 50, "ref-1")),
    ]


def test_the_first_charge_and_renewals_use_their_own_templates_with_the_plan_amount_and_next_date() -> None:
    first = charge_notice(USER_ID, SUMMARY, first=True)
    renewal = charge_notice(USER_ID, SUMMARY, first=False)

    assert (first.template, renewal.template) == ("subscription_activated", "renewal_receipt")
    assert first.context == {
        "plan": "Pro",
        "amount": "\N{INDIAN RUPEE SIGN}999.00 incl. GST",
        "credits": "500",
        "next_charge": "17 November 2026",
    }
    assert first.user_id == USER_ID


def test_a_missing_next_charge_date_is_stated_plainly() -> None:
    notice = charge_notice(USER_ID, ChargeSummary("Pro", 99_900, "INR", 500, None), first=False)

    assert notice.context["next_charge"] == "Not scheduled"
    assert formatted_date(None) == "Not scheduled"


def test_the_refund_notice_names_the_amount_credits_recovered_and_reference() -> None:
    notice = refund_notice(USER_ID, RefundSummary(1_234_500, "INR", 0, "abc"))

    assert notice.template == "refund_processed"
    assert notice.context == {
        "amount": "\N{INDIAN RUPEE SIGN}12,345.00",
        "credits_recovered": "0",
        "reference": "abc",
    }


def test_the_lifecycle_notices_name_the_plan_and_the_relevant_date() -> None:
    assert charge_failed_notice(USER_ID, "Pro", NEXT).context == {"plan": "Pro", "next_attempt": "17 November 2026"}
    assert halted_notice(USER_ID, "Pro").context == {"plan": "Pro"}
    assert cancellation_notice(USER_ID, "Pro", NEXT).context == {"plan": "Pro", "ends": "17 November 2026"}
    assert ended_notice(USER_ID, "Pro").context == {"plan": "Pro"}


@pytest.mark.parametrize("notice", all_notices(), ids=lambda notice: notice.template)
def test_every_notice_is_a_valid_renderable_billing_email(notice: BillingNotice) -> None:
    message = Notification(
        destination="asha@example.com", channel="email", template=notice.template, context=notice.context
    )

    rendered = render_email(message)

    assert "Pro" in rendered.text or notice.template == "refund_processed"
    assert "Motionile" in rendered.subject


class RecordingUsers:
    def __init__(self, email: str | None) -> None:
        self.email = email

    async def primary_verified_email(self, user_id: UUID) -> str | None:
        del user_id
        return self.email


def users_with(email: str | None) -> Callable[[AsyncSession], RecordingUsers]:
    def build(session: AsyncSession) -> RecordingUsers:
        del session
        return RecordingUsers(email)

    return build


class Queue:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, resources: Resources, session: AsyncSession, **options: Any) -> None:
        self.calls.append({"resources": resources, "session": session, **options})


async def test_the_mailer_queues_the_email_for_the_primary_verified_address(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = Queue()
    monkeypatch.setattr(notices_module, "UsersService", users_with("asha@example.com"))
    monkeypatch.setattr(notices_module, "enqueue_billing_email", queue)
    resources = cast("Resources", SimpleNamespace())

    await NoticeMailer(resources).send(AsyncSession(), halted_notice(USER_ID, "Pro"))

    [call] = queue.calls
    assert (call["email"], call["template"], call["context"]) == (
        "asha@example.com",
        "subscription_halted",
        {"plan": "Pro"},
    )
    assert call["resources"] is resources


async def test_the_mailer_sends_nothing_without_a_verified_email(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = Queue()
    monkeypatch.setattr(notices_module, "UsersService", users_with(None))
    monkeypatch.setattr(notices_module, "enqueue_billing_email", queue)

    await NoticeMailer(cast("Resources", SimpleNamespace())).send(AsyncSession(), ended_notice(USER_ID, "Pro"))

    assert queue.calls == []
