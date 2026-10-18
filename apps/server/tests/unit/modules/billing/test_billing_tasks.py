from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import orjson
import pytest
from procrastinate import App
from procrastinate.jobs import Job, Status
from procrastinate.testing import InMemoryConnector
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.settings import STRONG_SECRET, make_settings

from motionile.core.config import AppEnv, CatalogSettings, Settings, get_settings
from motionile.core.db import run_after_commit
from motionile.core.ids import new_id
from motionile.core.tasks.app import registered_task_app
from motionile.core.tasks.registry import TASK_MODULES
from motionile.entrypoints import worker
from motionile.modules.billing import tasks
from motionile.modules.billing.exceptions import WebhookProcessingError
from motionile.modules.billing.services.factory import BillingServices
from motionile.modules.billing.services.webhook_processor import ProcessingResult, ProcessingState
from motionile.modules.catalog import tasks as catalog_tasks

EXPECTED_SCHEDULES = {
    "motionile:billing.requeue_stuck_webhooks": "*/2 * * * *",
    "motionile:billing.reconcile_pending_orders": "*/15 * * * *",
    "motionile:billing.finalize_subscriptions": "*/15 * * * *",
    "motionile:billing.sync_subscriptions": "15 3 * * *",
    "motionile:billing.settlement_check": "0 4 * * *",
}


def schedules_of(app: App) -> dict[str, str]:
    registry: dict[tuple[str, str], Any] = vars(app.periodic_registry)["periodic_tasks"]
    return {entry.task.name: entry.cron for entry in registry.values()}


def queues_of(app: App) -> dict[str, str]:
    registered: dict[str, Any] = vars(app)["tasks"]
    return {name: task.queue for name, task in registered.items()}


@pytest.fixture
async def in_memory_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[App, InMemoryConnector]]:
    connector = InMemoryConnector()
    with registered_task_app().replace_connector(connector) as app:
        monkeypatch.setattr(app, "periodic_defaults", {"max_delay": -1})
        async with app.open_async():
            yield app, connector


def test_the_billing_task_module_is_loaded_by_every_process() -> None:
    assert "motionile.modules.billing.tasks" in TASK_MODULES


def test_the_periodic_tasks_are_registered_with_their_schedules() -> None:
    assert EXPECTED_SCHEDULES.items() <= schedules_of(registered_task_app()).items()
    assert EXPECTED_SCHEDULES.items() <= schedules_of(worker.app).items()


def test_every_task_runs_on_its_queue() -> None:
    queues = queues_of(registered_task_app())

    assert queues["motionile:billing.process_webhook_event"] == "billing"
    assert queues["motionile:billing.requeue_stuck_webhooks"] == "billing"
    assert queues["motionile:billing.reconcile_pending_orders"] == "billing"
    assert queues["motionile:billing.finalize_subscriptions"] == "billing"
    assert queues["motionile:billing.sync_subscriptions"] == "billing"
    assert queues["motionile:billing.settlement_check"] == "billing"
    assert queues["motionile:billing.revalidate_products"] == "default"


def job_after(attempts: int) -> Job:
    return Job(queue="billing", lock=None, queueing_lock=None, task_name="x", attempts=attempts)


def test_webhook_retries_back_off_exponentially_and_stop_before_the_attempt_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BILLING_WEBHOOK_MAX_ATTEMPTS", "5")
    get_settings.cache_clear()
    strategy = tasks.WebhookRetryStrategy(exponential_wait=2)

    delays: list[datetime] = []
    for attempts in range(4):
        decision = strategy.get_retry_decision(exception=RuntimeError("boom"), job=job_after(attempts))
        assert decision is not None
        assert decision.retry_at is not None
        delays.append(decision.retry_at)

    assert delays == sorted(delays)
    assert strategy.get_retry_decision(exception=RuntimeError("boom"), job=job_after(4)) is None


def test_the_default_retry_limit_follows_the_settings() -> None:
    strategy = tasks.WebhookRetryStrategy(exponential_wait=2)
    limit = get_settings().billing.webhook_max_attempts

    assert strategy.get_retry_decision(exception=RuntimeError(), job=job_after(limit - 2)) is not None
    assert strategy.get_retry_decision(exception=RuntimeError(), job=job_after(limit - 1)) is None


@dataclass
class StubProcessor:
    outcome: Exception | ProcessingResult
    calls: list[tuple[UUID, bool]] = field(default_factory=list[tuple[UUID, bool]])

    async def process(self, event_row_id: UUID, *, force: bool = False) -> ProcessingResult:
        self.calls.append((event_row_id, force))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def install_services(monkeypatch: pytest.MonkeyPatch, **services: object) -> None:
    @asynccontextmanager
    async def fake_worker_services(application_name: str) -> AsyncGenerator[BillingServices]:
        del application_name
        yield cast("BillingServices", SimpleNamespace(**services))

    monkeypatch.setattr(tasks, "worker_services", fake_worker_services)


async def test_the_processing_task_hands_the_event_to_the_processor(
    in_memory_app: tuple[App, InMemoryConnector], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, connector = in_memory_app
    processor = StubProcessor(ProcessingResult(ProcessingState.PROCESSED, 1))
    install_services(monkeypatch, processor=processor)
    event_row_id = new_id()
    await tasks.process_webhook_event.defer_async(event_row_id=str(event_row_id), force=True)

    await app.run_worker_async(wait=False, install_signal_handlers=False)

    assert processor.calls == [(event_row_id, True)]
    assert [job["status"] for job in connector.jobs.values()] == [Status.SUCCEEDED.value]


async def test_a_failed_attempt_is_retried_by_the_queue(
    in_memory_app: tuple[App, InMemoryConnector], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, connector = in_memory_app
    processor = StubProcessor(WebhookProcessingError("event", 1))
    install_services(monkeypatch, processor=processor)
    await tasks.process_webhook_event.defer_async(event_row_id=str(new_id()), force=False)

    await app.run_worker_async(wait=False, install_signal_handlers=False)

    [job] = connector.jobs.values()
    assert job["status"] == Status.TODO.value
    assert job["attempts"] == 1
    assert job["scheduled_at"] is not None


async def test_the_final_attempt_is_not_retried(
    in_memory_app: tuple[App, InMemoryConnector], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, connector = in_memory_app
    processor = StubProcessor(ProcessingResult(ProcessingState.FAILED_FINAL, 10))
    install_services(monkeypatch, processor=processor)
    await tasks.process_webhook_event.defer_async(event_row_id=str(new_id()), force=False)

    await app.run_worker_async(wait=False, install_signal_handlers=False)

    assert [job["status"] for job in connector.jobs.values()] == [Status.SUCCEEDED.value]


@dataclass
class StubRequeuer:
    async def requeue_stuck(self) -> int:
        return 3


@dataclass
class StubReconciliation:
    runs: int = 0

    async def reconcile_pending_orders(self) -> Any:
        self.runs += 1
        return SimpleNamespace(checked=1, repaired=1, mismatch=0, errors=0)


@pytest.mark.parametrize("task_name", ["requeue_stuck_webhooks", "reconcile_pending_orders"])
async def test_scheduled_runs_accept_the_timestamp_procrastinate_passes(
    in_memory_app: tuple[App, InMemoryConnector], monkeypatch: pytest.MonkeyPatch, task_name: str
) -> None:
    app, connector = in_memory_app
    reconciliation = StubReconciliation()
    install_services(monkeypatch, requeuer=StubRequeuer(), reconciliation=reconciliation)
    await getattr(tasks, task_name).defer_async(timestamp=1_760_000_000)

    await app.run_worker_async(wait=False, install_signal_handlers=False)

    assert [job["status"] for job in connector.jobs.values()] == [Status.SUCCEEDED.value]
    assert reconciliation.runs == (1 if task_name == "reconcile_pending_orders" else 0)


@dataclass
class StubFinalizer:
    runs: int = 0

    async def finalize(self) -> Any:
        self.runs += 1
        return SimpleNamespace(cancelled=2, expired=1)


@dataclass
class StubSync:
    runs: int = 0

    async def run(self) -> Any:
        self.runs += 1
        return SimpleNamespace(checked=3, repaired=1, mismatch=0, errors=0)


@dataclass
class StubSettlementCheck:
    result: Any
    runs: int = 0

    async def run(self) -> Any:
        self.runs += 1
        return self.result


@pytest.mark.parametrize("task_name", ["finalize_subscriptions", "sync_subscriptions", "settlement_check"])
async def test_the_new_scheduled_runs_call_their_services_with_the_timestamp_procrastinate_passes(
    in_memory_app: tuple[App, InMemoryConnector], monkeypatch: pytest.MonkeyPatch, task_name: str
) -> None:
    app, connector = in_memory_app
    finalizer = StubFinalizer()
    sync = StubSync()
    check = StubSettlementCheck(
        SimpleNamespace(day=date(2026, 10, 17), checked=2, mismatches=0, report_key="billing/x.json")
    )
    install_services(monkeypatch, subscriptions=SimpleNamespace(finalizer=finalizer, sync=sync), settlement_check=check)
    await getattr(tasks, task_name).defer_async(timestamp=1_760_000_000)

    await app.run_worker_async(wait=False, install_signal_handlers=False)

    assert [job["status"] for job in connector.jobs.values()] == [Status.SUCCEEDED.value]
    assert (finalizer.runs, sync.runs, check.runs) == {
        "finalize_subscriptions": (1, 0, 0),
        "sync_subscriptions": (0, 1, 0),
        "settlement_check": (0, 0, 1),
    }[task_name]


async def test_a_settlement_check_that_finds_the_day_already_done_succeeds_quietly(
    in_memory_app: tuple[App, InMemoryConnector], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, connector = in_memory_app
    check = StubSettlementCheck(None)
    install_services(monkeypatch, settlement_check=check)
    await tasks.settlement_check.defer_async(timestamp=1_760_000_000)

    await app.run_worker_async(wait=False, install_signal_handlers=False)

    assert check.runs == 1
    assert [job["status"] for job in connector.jobs.values()] == [Status.SUCCEEDED.value]


async def test_events_are_queued_only_after_the_transaction_commits(
    in_memory_app: tuple[App, InMemoryConnector],
) -> None:
    _, connector = in_memory_app
    session = AsyncSession()
    event_row_id = new_id()

    tasks.defer_event_processing(session, event_row_id, True)
    assert connector.jobs == {}
    await run_after_commit(session)

    [job] = connector.jobs.values()
    assert job["queue_name"] == "billing"
    assert job["task_name"] == "motionile:billing.process_webhook_event"
    assert job["args"] == {"event_row_id": str(event_row_id), "force": True}


async def test_product_revalidation_is_queued_on_the_default_queue_after_commit(
    in_memory_app: tuple[App, InMemoryConnector], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, connector = in_memory_app
    pushed: list[list[str]] = []

    async def capture(tags: list[str]) -> None:
        pushed.append(tags)

    monkeypatch.setattr(tasks, "push_revalidation", capture)
    session = AsyncSession()

    tasks.defer_product_revalidation(session)
    assert connector.jobs == {}
    await run_after_commit(session)
    [job] = connector.jobs.values()
    assert (job["queue_name"], job["task_name"]) == ("default", "motionile:billing.revalidate_products")

    await app.run_worker_async(wait=False, install_signal_handlers=False)

    assert pushed == [["billing-products"]]


def test_the_worker_hooks_name_the_processing_task() -> None:
    hooks = tasks.worker_hooks()

    assert hooks.process_task_name == "motionile:billing.process_webhook_event"
    assert hooks.dispatch is tasks.defer_event_processing


@dataclass
class RecordingClient:
    status_code: int = 200
    requests: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    async def request(self, method: str, url: str, **options: Any) -> Any:
        self.requests.append({"method": method, "url": url, **options})
        return SimpleNamespace(status_code=self.status_code)


@dataclass
class RecordingResources:
    client: RecordingClient
    closed: bool = False

    @property
    def provider_clients(self) -> dict[str, RecordingClient]:
        return {"catalog_revalidation": self.client}

    async def aclose(self) -> None:
        self.closed = True


def install_revalidation(
    monkeypatch: pytest.MonkeyPatch, client: RecordingClient, *, env: AppEnv = AppEnv.CI, secret: bool = True
) -> RecordingResources:
    settings = make_settings(env)
    if secret:
        settings = settings.model_copy(update={"catalog": CatalogSettings(revalidation_secret=STRONG_SECRET)})
    resources = RecordingResources(client)
    monkeypatch.setattr(catalog_tasks, "get_settings", lambda: settings)

    def build(_settings: Settings, *, application_name: str) -> RecordingResources:
        del application_name
        return resources

    monkeypatch.setattr(catalog_tasks, "build_resources", build)
    return resources

    monkeypatch.setattr(
        catalog_tasks, "build_resources", lambda _settings, *, application_name: build(application_name)
    )
    return resources


async def test_the_shared_revalidation_posts_the_tags_with_the_bearer_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    client = RecordingClient()
    resources = install_revalidation(monkeypatch, client)

    await catalog_tasks.push_revalidation(["billing-products"])

    [request] = client.requests
    assert request["method"] == "POST"
    assert request["url"].endswith("/api/revalidate")
    assert request["headers"]["Authorization"].startswith("Bearer ")
    assert orjson.loads(request["content"]) == {"tags": ["billing-products"]}
    assert resources.closed


async def test_a_rejected_revalidation_is_an_error_and_still_releases_the_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = install_revalidation(monkeypatch, RecordingClient(status_code=401))

    with pytest.raises(RuntimeError, match="revalidation failed"):
        await catalog_tasks.push_revalidation(["billing-products"])

    assert resources.closed


async def test_a_missing_secret_is_tolerated_only_locally(monkeypatch: pytest.MonkeyPatch) -> None:
    client = RecordingClient()
    install_revalidation(monkeypatch, client, env=AppEnv.LOCAL, secret=False)
    await catalog_tasks.push_revalidation(["billing-products"])
    assert client.requests == []

    install_revalidation(monkeypatch, client, env=AppEnv.CI, secret=False)
    with pytest.raises(RuntimeError, match="secret is missing"):
        await catalog_tasks.push_revalidation(["billing-products"])


async def test_the_catalog_task_shares_the_revalidation_contract(
    in_memory_app: tuple[App, InMemoryConnector], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, _ = in_memory_app
    client = RecordingClient()
    install_revalidation(monkeypatch, client)
    await catalog_tasks.revalidate_catalog.defer_async(tags=["catalog"])

    await app.run_worker_async(wait=False, install_signal_handlers=False)

    assert orjson.loads(client.requests[0]["content"]) == {"tags": ["catalog"]}
