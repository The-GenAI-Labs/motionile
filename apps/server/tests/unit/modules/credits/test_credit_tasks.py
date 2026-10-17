from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import create_autospec
from uuid import UUID

import pytest
from procrastinate import App
from procrastinate.jobs import Status
from procrastinate.testing import InMemoryConnector
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.resources import make_resources
from tests.fakes.settings import make_settings
from tests.unit.modules.credits.conftest import Harness

from motionile.core.ids import new_id
from motionile.core.resources import Resources
from motionile.core.tasks.app import registered_task_app
from motionile.core.tasks.registry import RegisteredTask
from motionile.entrypoints import worker
from motionile.modules.credits import CreditsService, tasks
from motionile.modules.credits.domain import ExpiryResult, ReleaseResult, ReminderBatch

EXPECTED_SCHEDULES = {
    "motionile:credits.expire_lots": "*/15 * * * *",
    "motionile:credits.release_stale_reservations": "*/5 * * * *",
    "motionile:credits.send_expiry_reminders": "0 * * * *",
    "motionile:credits.check_integrity": "30 2 * * *",
}


@dataclass
class Alerts:
    raised: list[tuple[str, dict[str, object]]]


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> Alerts:
    recorded = Alerts(raised=[])

    def capture(code: str, **fields: object) -> None:
        recorded.raised.append((code, fields))

    monkeypatch.setattr(tasks, "raise_alert", capture)
    return recorded


@pytest.fixture
async def in_memory_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[App, InMemoryConnector]]:
    connector = InMemoryConnector()
    with registered_task_app().replace_connector(connector) as app:
        monkeypatch.setattr(app, "periodic_defaults", {"max_delay": -1})
        async with app.open_async():
            yield app, connector


async def make_due_users(harness: Harness, count: int) -> list[UUID]:
    users = [new_id() for _ in range(count)]
    for user in users:
        await harness.grant(10, expires_in=timedelta(days=1), user_id=user)
    harness.clock.advance(timedelta(days=2))
    return users


async def test_expiry_sweep_expires_every_due_wallet(harness: Harness) -> None:
    users = await make_due_users(harness, 3)

    expired = await tasks.sweep_expired_lots(harness.store.transaction, harness.service)

    assert expired == 30
    assert all(harness.wallet(user) == (0, 0) for user in users)
    assert await tasks.sweep_expired_lots(harness.store.transaction, harness.service) == 0


async def test_expiry_sweep_walks_every_batch(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "BATCH_SIZE", 2)
    users = await make_due_users(harness, 5)

    assert await tasks.sweep_expired_lots(harness.store.transaction, harness.service) == 50
    assert all(harness.wallet(user) == (0, 0) for user in users)


async def test_expiry_sweep_isolates_failures_and_reports_them(harness: Harness) -> None:
    users = sorted(await make_due_users(harness, 3))

    class Flaky(CreditsService):
        async def expire_due_lots(self, session: AsyncSession, user_id: UUID) -> ExpiryResult:
            if user_id == users[1]:
                raise RuntimeError("boom")
            return await super().expire_due_lots(session, user_id)

    flaky = Flaky(harness.clock, make_settings().billing, store_factory=harness.store, audit=harness.audit)

    with pytest.raises(tasks.SweepFailedError) as raised:
        await tasks.sweep_expired_lots(harness.store.transaction, flaky)

    assert raised.value.failures == 1
    assert [harness.wallet(user)[0] for user in users] == [0, 10, 0]


async def test_stale_reservation_sweep_releases_only_expired_holds(harness: Harness) -> None:
    await harness.grant(100)
    stale = await harness.reserve(30, ttl=timedelta(minutes=5))
    live = await harness.reserve(20, ttl=timedelta(hours=2))
    harness.clock.advance(timedelta(minutes=10))

    released = await tasks.sweep_stale_reservations(harness.store.transaction, harness.service)

    assert released == 1
    assert harness.store.reservations[stale.id].status == "expired"
    assert harness.store.reservations[live.id].status == "active"
    assert harness.wallet() == (100, 20)
    assert await tasks.sweep_stale_reservations(harness.store.transaction, harness.service) == 0


async def test_stale_reservation_sweep_walks_every_batch(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "BATCH_SIZE", 2)
    await harness.grant(100)
    for _ in range(5):
        await harness.reserve(1, ttl=timedelta(minutes=1))
    harness.clock.advance(timedelta(minutes=2))

    assert await tasks.sweep_stale_reservations(harness.store.transaction, harness.service) == 5
    assert harness.wallet() == (100, 0)


async def test_stale_reservation_sweep_reports_failures_after_processing_the_rest(harness: Harness) -> None:
    await harness.grant(100)
    reservations = sorted([(await harness.reserve(1, ttl=timedelta(minutes=1))).id for _ in range(3)])
    harness.clock.advance(timedelta(minutes=2))

    class Flaky(CreditsService):
        async def release_stale(self, session: AsyncSession, reservation_id: UUID) -> ReleaseResult | None:
            if reservation_id == reservations[0]:
                raise RuntimeError("boom")
            return await super().release_stale(session, reservation_id)

    flaky = Flaky(harness.clock, make_settings().billing, store_factory=harness.store, audit=harness.audit)

    with pytest.raises(tasks.SweepFailedError):
        await tasks.sweep_stale_reservations(harness.store.transaction, flaky)

    assert harness.wallet() == (100, 1)


async def test_reminders_resolve_emails_and_send_once_per_lot(harness: Harness) -> None:
    mailed, silent = new_id(), new_id()
    await harness.grant(10, expires_in=timedelta(days=3), user_id=mailed)
    await harness.grant(5, expires_in=timedelta(days=5), user_id=mailed)
    await harness.grant(8, expires_in=timedelta(days=2), user_id=silent)
    sent: list[tuple[str, ReminderBatch]] = []

    async def resolve(session: AsyncSession, user_id: UUID) -> str | None:
        del session
        return "mailed@example.com" if user_id == mailed else None

    def send(session: AsyncSession, email: str, batch: ReminderBatch) -> None:
        del session
        sent.append((email, batch))

    queued = await tasks.remind_expiring_credits(harness.store.transaction, harness.service, resolve, send)
    again = await tasks.remind_expiring_credits(harness.store.transaction, harness.service, resolve, send)

    assert (queued, again) == (1, 0)
    assert [(email, batch.user_id, batch.credits) for email, batch in sent] == [("mailed@example.com", mailed, 15)]
    assert sent[0][1].expires_at == harness.clock.now() + timedelta(days=3)
    assert all(lot.expiry_reminder_sent_at is not None for lot in harness.store.lots.values())


async def test_reminder_marks_roll_back_with_the_transaction(harness: Harness) -> None:
    user = new_id()
    await harness.grant(10, expires_in=timedelta(days=3), user_id=user)

    async def resolve(session: AsyncSession, user_id: UUID) -> str | None:
        del session, user_id
        return "x@example.com"

    def send(session: AsyncSession, email: str, batch: ReminderBatch) -> None:
        del session, email, batch
        raise RuntimeError("queue unavailable")

    with pytest.raises(RuntimeError):
        await tasks.remind_expiring_credits(harness.store.transaction, harness.service, resolve, send)

    assert all(lot.expiry_reminder_sent_at is None for lot in harness.store.lots.values())


async def test_reminder_sender_queues_a_credits_expiring_email(monkeypatch: pytest.MonkeyPatch) -> None:
    resources = make_resources(make_settings())
    calls: list[dict[str, object]] = []

    def capture(built: Resources, session: AsyncSession, **arguments: object) -> None:
        del session
        assert built is resources
        calls.append(arguments)

    monkeypatch.setattr(tasks, "enqueue_billing_email", capture)

    tasks.reminder_sender(resources)(
        create_autospec(AsyncSession, instance=True),
        "user@example.com",
        ReminderBatch(user_id=new_id(), credits=150, expires_at=datetime(2026, 11, 3, 8, 0, tzinfo=UTC)),
    )

    await resources.aclose()
    assert calls == [
        {
            "email": "user@example.com",
            "template": "credits_expiring",
            "context": {"credits": "150", "expires_on": "03 November 2026"},
        }
    ]


async def test_integrity_task_raises_an_alert_with_every_offending_user(harness: Harness, alerts: Alerts) -> None:
    await harness.grant(100)
    broken_user = new_id()
    await harness.grant(50, user_id=broken_user)
    for user in (harness.user_id, broken_user):
        wallet = harness.store.wallets[user]
        harness.store.wallets[user] = replace(wallet, balance=wallet.balance + 1)
    snapshot = harness.store.snapshot()

    violations = await tasks.verify_integrity(harness.store.transaction, harness.service)

    assert {violation.user_id for violation in violations} == {harness.user_id, broken_user}
    assert len(alerts.raised) == 1
    code, fields = alerts.raised[0]
    assert code == "credit_integrity_violation"
    assert set(cast("list[str]", fields["user_ids"])) == {str(harness.user_id), str(broken_user)}
    details = cast("list[dict[str, Any]]", fields["violations"])
    first = next(item for item in details if item["userId"] == str(harness.user_id))
    assert {"invariant": "balance_equals_ledger_delta_sum", "expected": 100, "actual": 101} in first["problems"]
    assert harness.store.snapshot() == snapshot


async def test_integrity_task_is_silent_when_every_wallet_is_consistent(harness: Harness, alerts: Alerts) -> None:
    await harness.grant(100)
    reservation = await harness.reserve(10)
    await harness.service.commit(harness.session, reservation.id, 10, "commit:ok")

    violations = await tasks.verify_integrity(harness.store.transaction, harness.service)

    assert violations == []
    assert alerts.raised == []


def schedules_of(app: App) -> dict[str, str]:
    registry: dict[tuple[str, str], Any] = vars(app.periodic_registry)["periodic_tasks"]
    return {entry.task.name: entry.cron for entry in registry.values()}


def queues_of(app: App) -> dict[str, str]:
    registered: dict[str, Any] = vars(app)["tasks"]
    return {name: task.queue for name, task in registered.items()}


def test_all_credit_schedules_are_registered_on_the_billing_queue() -> None:
    app = registered_task_app()

    assert EXPECTED_SCHEDULES.items() <= schedules_of(app).items()
    queues = queues_of(app)
    assert {queues[name] for name in EXPECTED_SCHEDULES} == {"billing"}


def test_the_worker_entrypoint_picks_up_the_credit_schedules() -> None:
    assert EXPECTED_SCHEDULES.items() <= schedules_of(worker.app).items()
    assert set(EXPECTED_SCHEDULES) <= set(queues_of(worker.app))


@pytest.mark.parametrize(
    ("task", "application_name"),
    [
        (tasks.expire_lots, "motionile-credits-expiry"),
        (tasks.release_stale_reservations, "motionile-credits-reservations"),
        (tasks.check_integrity, "motionile-credits-integrity"),
    ],
)
async def test_scheduled_runs_accept_the_timestamp_procrastinate_passes(
    in_memory_app: tuple[App, InMemoryConnector],
    monkeypatch: pytest.MonkeyPatch,
    task: RegisteredTask,
    application_name: str,
) -> None:
    app, connector = in_memory_app
    ran: list[str] = []

    async def fake_run_sweep(name: str, sweep: Callable[..., Awaitable[object]]) -> None:
        del sweep
        ran.append(name)

    monkeypatch.setattr(tasks, "run_sweep", fake_run_sweep)
    await task.defer_async(timestamp=1_760_000_000)

    await app.run_worker_async(wait=False, install_signal_handlers=False)

    assert ran == [application_name]
    assert [job["status"] for job in connector.jobs.values()] == [Status.SUCCEEDED.value]
