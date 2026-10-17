from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import Any
from uuid import UUID

import orjson
import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.settings import make_settings
from tests.unit.modules.billing.conftest import PACK_CREDITS, BillingHarness

from motionile.core.errors import ServiceUnavailableError
from motionile.core.ids import new_id
from motionile.modules.billing.exceptions import (
    InvalidWebhookPayloadError,
    InvalidWebhookSignatureError,
    WebhookEventIdMissingError,
    WebhookEventNotFoundError,
    WebhookEventNotReprocessableError,
    WebhookProcessingError,
    WebhookTooLargeError,
)
from motionile.modules.billing.ports import Transaction
from motionile.modules.billing.razorpay.credentials import razorpay_credentials
from motionile.modules.billing.razorpay.exceptions import RazorpayNotConfiguredError
from motionile.modules.billing.razorpay.fake_entities import FAKE_ACCOUNT_ID
from motionile.modules.billing.razorpay.fake_events import (
    WebhookEntities,
    WebhookEventName,
    build_envelope,
)
from motionile.modules.billing.razorpay.fake_simulator import PaymentOutcome
from motionile.modules.billing.razorpay.fake_store import EntityKind
from motionile.modules.billing.razorpay.models import RazorpayPayment
from motionile.modules.billing.razorpay.signatures import sign_webhook
from motionile.modules.billing.records import NewWebhookEvent, WebhookEventRecord
from motionile.modules.billing.services.payment_events import PaymentEventHandlers
from motionile.modules.billing.services.webhook_processor import (
    ProcessingState,
    ProcessorPorts,
    WebhookProcessor,
    describe_failure,
)
from motionile.modules.billing.services.webhook_recovery import (
    RequeuePolicy,
    WebhookRequeuer,
    reprocess_event_with,
)
from motionile.modules.billing.services.webhook_registry import (
    PROCESSED,
    DuplicateHandlerError,
    HandlerRegistry,
    Outcome,
    ignored,
)
from motionile.modules.billing.services.webhooks import MAX_BODY_BYTES, WebhookReceiver, event_time
from motionile.modules.billing.states import OrderStatus, WebhookEventStatus

WEBHOOK_SECRET = razorpay_credentials(make_settings()).webhook_secret
MAX_ATTEMPTS = 3


@dataclass
class Dispatcher:
    calls: list[tuple[UUID, bool]] = field(default_factory=list[tuple[UUID, bool]])

    def __call__(self, session: AsyncSession, event_row_id: UUID, force: bool) -> None:
        del session
        self.calls.append((event_row_id, force))


def envelope_body(event: str = "payment.captured", created_at: int | None = 1_760_000_000) -> bytes:
    document: dict[str, Any] = {"entity": "event", "event": event, "payload": {"payment": {"entity": {"id": "pay_1"}}}}
    if created_at is not None:
        document["created_at"] = created_at
    return orjson.dumps(document)


def signed(body: bytes) -> str:
    return sign_webhook(body, WEBHOOK_SECRET)


def receiver_for(
    harness: BillingHarness, dispatcher: Dispatcher, secret: SecretStr = WEBHOOK_SECRET
) -> WebhookReceiver:
    return WebhookReceiver(
        harness.world.transaction, harness.clock, lambda: secret, dispatcher, store_factory=harness.billing
    )


async def test_a_signed_event_is_stored_once_and_queued(billing_harness: BillingHarness) -> None:
    dispatcher = Dispatcher()
    body = envelope_body()

    status = await receiver_for(billing_harness, dispatcher).receive(body, signed(body), "evt_1")

    assert status == "received"
    [stored] = billing_harness.billing.events.values()
    assert (stored.provider, stored.event_id, stored.event_type) == ("razorpay", "evt_1", "payment.captured")
    assert stored.status is WebhookEventStatus.RECEIVED
    assert stored.attempts == 0
    assert stored.event_created_at == event_time(1_760_000_000)
    assert stored.received_at == billing_harness.clock.now()
    assert stored.payload["payload"]["payment"]["entity"]["id"] == "pay_1"
    assert dispatcher.calls == [(stored.id, False)]


async def test_a_replayed_event_id_is_a_duplicate_and_queues_nothing(billing_harness: BillingHarness) -> None:
    dispatcher = Dispatcher()
    receiver = receiver_for(billing_harness, dispatcher)
    body = envelope_body()
    await receiver.receive(body, signed(body), "evt_1")

    again = await receiver.receive(body, signed(body), "evt_1")

    assert again == "duplicate"
    assert len(billing_harness.billing.events) == 1
    assert len(dispatcher.calls) == 1


async def test_a_duplicate_of_an_event_stuck_in_received_is_queued_again_after_a_minute(
    billing_harness: BillingHarness,
) -> None:
    dispatcher = Dispatcher()
    receiver = receiver_for(billing_harness, dispatcher)
    body = envelope_body()
    await receiver.receive(body, signed(body), "evt_1")
    billing_harness.clock.advance(timedelta(seconds=59))
    await receiver.receive(body, signed(body), "evt_1")
    assert len(dispatcher.calls) == 1

    billing_harness.clock.advance(timedelta(seconds=2))
    status = await receiver.receive(body, signed(body), "evt_1")

    assert status == "duplicate"
    assert len(dispatcher.calls) == 2
    assert dispatcher.calls[0] == dispatcher.calls[1]


@pytest.mark.parametrize(
    "settled", [WebhookEventStatus.PROCESSED, WebhookEventStatus.IGNORED, WebhookEventStatus.FAILED]
)
async def test_a_duplicate_of_an_event_past_received_is_never_requeued(
    billing_harness: BillingHarness, settled: WebhookEventStatus
) -> None:
    dispatcher = Dispatcher()
    receiver = receiver_for(billing_harness, dispatcher)
    body = envelope_body()
    await receiver.receive(body, signed(body), "evt_1")
    [stored] = billing_harness.billing.events.values()
    billing_harness.billing.events[stored.id] = replace(stored, status=settled)
    billing_harness.clock.advance(timedelta(hours=1))

    await receiver.receive(body, signed(body), "evt_1")

    assert len(dispatcher.calls) == 1


@pytest.mark.parametrize("signature", [None, "", "0" * 64, "xyz", "A" * 64])
async def test_a_missing_or_wrong_signature_is_rejected_and_stores_nothing(
    billing_harness: BillingHarness, signature: str | None
) -> None:
    dispatcher = Dispatcher()

    with pytest.raises(InvalidWebhookSignatureError) as raised:
        await receiver_for(billing_harness, dispatcher).receive(envelope_body(), signature, "evt_1")

    assert (raised.value.status_code, raised.value.code) == (401, "invalid_webhook_signature")
    assert billing_harness.billing.events == {}
    assert dispatcher.calls == []


async def test_a_signature_for_another_body_is_rejected(billing_harness: BillingHarness) -> None:
    other = envelope_body("payment.failed")

    with pytest.raises(InvalidWebhookSignatureError):
        await receiver_for(billing_harness, Dispatcher()).receive(envelope_body(), signed(other), "evt_1")


async def test_a_signature_made_with_the_wrong_secret_is_rejected(billing_harness: BillingHarness) -> None:
    body = envelope_body()
    forged = sign_webhook(body, SecretStr("other-secret"))

    with pytest.raises(InvalidWebhookSignatureError):
        await receiver_for(billing_harness, Dispatcher()).receive(body, forged, "evt_1")


@pytest.mark.parametrize("event_id", [None, "", "has space", "x" * 129, "tab\tid"])
async def test_a_missing_or_malformed_event_id_is_rejected(
    billing_harness: BillingHarness, event_id: str | None
) -> None:
    body = envelope_body()

    with pytest.raises(WebhookEventIdMissingError) as raised:
        await receiver_for(billing_harness, Dispatcher()).receive(body, signed(body), event_id)

    assert raised.value.status_code == 400
    assert billing_harness.billing.events == {}


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        b"42",
        b'{"payload": {}}',
        b'{"event": ""}',
        b'{"event": 5}',
        b'{"event": "x", "created_at": -1}',
    ],
)
async def test_a_signed_but_unusable_body_is_rejected(billing_harness: BillingHarness, body: bytes) -> None:
    with pytest.raises(InvalidWebhookPayloadError):
        await receiver_for(billing_harness, Dispatcher()).receive(body, signed(body), "evt_1")

    assert billing_harness.billing.events == {}


async def test_an_oversized_body_is_refused_before_it_is_verified(billing_harness: BillingHarness) -> None:
    body = b" " * (MAX_BODY_BYTES + 1)

    with pytest.raises(WebhookTooLargeError):
        await receiver_for(billing_harness, Dispatcher()).receive(body, None, "evt_1")


async def test_an_unconfigured_secret_makes_the_endpoint_unavailable(billing_harness: BillingHarness) -> None:
    def unconfigured() -> SecretStr:
        raise RazorpayNotConfiguredError

    receiver = WebhookReceiver(
        billing_harness.world.transaction,
        billing_harness.clock,
        unconfigured,
        Dispatcher(),
        store_factory=billing_harness.billing,
    )

    with pytest.raises(ServiceUnavailableError) as raised:
        await receiver.receive(envelope_body(), "0" * 64, "evt_1")

    assert raised.value.code == "webhook_not_configured"


@pytest.mark.parametrize("value", [None, 10**20])
def test_unrepresentable_event_times_are_dropped(value: int | None) -> None:
    assert event_time(value) is None


async def test_unknown_event_types_are_stored(billing_harness: BillingHarness) -> None:
    body = envelope_body("account.updated", created_at=None)

    status = await receiver_for(billing_harness, Dispatcher()).receive(body, signed(body), "evt_1")

    assert status == "received"
    [stored] = billing_harness.billing.events.values()
    assert (stored.event_type, stored.event_created_at) == ("account.updated", None)


@dataclass
class Alerts:
    raised: list[tuple[str, dict[str, Any]]] = field(default_factory=list[tuple[str, dict[str, Any]]])

    def __call__(self, code: str, **fields: object) -> None:
        self.raised.append((code, dict(fields)))


@dataclass
class Handlers:
    calls: int = 0
    failures_left: int = 0
    mutate: Any = None
    outcome: Outcome = PROCESSED

    async def __call__(self, session: AsyncSession, event: WebhookEventRecord) -> Outcome:
        del session, event
        self.calls += 1
        if self.mutate is not None:
            self.mutate()
        if self.failures_left > 0:
            self.failures_left -= 1
            message = "boom: sensitive customer@example.com 4111111111111111"
            raise RuntimeError(message)
        return self.outcome


@dataclass
class ProcessorSetup:
    harness: BillingHarness
    handlers: Handlers
    alerts: Alerts
    registry: HandlerRegistry
    processor: WebhookProcessor
    savepoints: list[str]


def make_processor(
    harness: BillingHarness, handlers: Handlers, *, transaction: Transaction | None = None
) -> ProcessorSetup:
    alerts = Alerts()
    savepoints: list[str] = []
    registry = HandlerRegistry()
    registry.register_handler("payment.captured", handlers)

    @asynccontextmanager
    async def savepoint(session: AsyncSession) -> AsyncGenerator[None]:
        del session
        billing_state = harness.billing.snapshot()
        credits_state = harness.credits_store.snapshot()
        savepoints.append("opened")
        try:
            yield
        except BaseException:
            harness.billing.restore(billing_state)
            harness.credits_store.restore(credits_state)
            savepoints.append("rolled_back")
            raise

    processor = WebhookProcessor(
        transaction or harness.world.transaction,
        registry,
        harness.clock,
        lambda: MAX_ATTEMPTS,
        ProcessorPorts(store_factory=harness.billing, savepoint=savepoint, alert=alerts),
    )
    return ProcessorSetup(harness, handlers, alerts, registry, processor, savepoints)


async def store_event(harness: BillingHarness, event_type: str = "payment.captured") -> UUID:
    event = NewWebhookEvent(
        id=new_id(),
        provider="razorpay",
        event_id=f"evt_{new_id().hex}",
        event_type=event_type,
        event_created_at=None,
        payload={},
        received_at=harness.clock.now(),
    )
    assert await harness.billing.insert_event(event)
    return event.id


async def test_a_handled_event_ends_processed(billing_harness: BillingHarness) -> None:
    setup = make_processor(billing_harness, Handlers())
    event_id = await store_event(billing_harness)

    result = await setup.processor.process(event_id)

    assert (result.state, result.attempts) == (ProcessingState.PROCESSED, 1)
    stored = billing_harness.billing.events[event_id]
    assert stored.status is WebhookEventStatus.PROCESSED
    assert stored.attempts == 1
    assert stored.processed_at == billing_harness.clock.now()
    assert (stored.last_error, stored.ignored_reason) == (None, None)


async def test_an_event_type_without_a_handler_is_ignored_as_unhandled(billing_harness: BillingHarness) -> None:
    setup = make_processor(billing_harness, Handlers())
    event_id = await store_event(billing_harness, "subscription.charged")

    result = await setup.processor.process(event_id)

    assert result.state is ProcessingState.IGNORED
    stored = billing_harness.billing.events[event_id]
    assert (stored.status, stored.ignored_reason) == (WebhookEventStatus.IGNORED, "unhandled_event")


async def test_a_handler_can_ignore_an_event_with_a_reason(billing_harness: BillingHarness) -> None:
    setup = make_processor(billing_harness, Handlers(outcome=ignored("unknown_entity")))
    event_id = await store_event(billing_harness)

    await setup.processor.process(event_id)

    stored = billing_harness.billing.events[event_id]
    assert (stored.status, stored.ignored_reason) == (WebhookEventStatus.IGNORED, "unknown_entity")


async def test_a_settled_event_is_skipped_unless_forced(billing_harness: BillingHarness) -> None:
    handlers = Handlers()
    setup = make_processor(billing_harness, handlers)
    event_id = await store_event(billing_harness)
    await setup.processor.process(event_id)

    skipped = await setup.processor.process(event_id)
    forced = await setup.processor.process(event_id, force=True)

    assert skipped.state is ProcessingState.SKIPPED
    assert forced.state is ProcessingState.PROCESSED
    assert handlers.calls == 2
    assert billing_harness.billing.events[event_id].attempts == 2


async def test_an_unknown_event_row_is_reported_missing(billing_harness: BillingHarness) -> None:
    setup = make_processor(billing_harness, Handlers())

    assert (await setup.processor.process(new_id())).state is ProcessingState.MISSING


async def test_a_committed_processing_event_is_left_alone(billing_harness: BillingHarness) -> None:
    handlers = Handlers()
    setup = make_processor(billing_harness, handlers)
    event_id = await store_event(billing_harness)
    event = billing_harness.billing.events[event_id]
    billing_harness.billing.events[event_id] = replace(event, status=WebhookEventStatus.PROCESSING)

    assert (await setup.processor.process(event_id)).state is ProcessingState.SKIPPED
    assert handlers.calls == 0


async def test_a_failing_handler_marks_the_event_failed_rolls_back_its_work_and_asks_for_a_retry(
    billing_harness: BillingHarness,
) -> None:
    handlers = Handlers(failures_left=1)
    handlers.mutate = billing_harness.billing.products.clear
    setup = make_processor(billing_harness, handlers)
    event_id = await store_event(billing_harness)

    with pytest.raises(WebhookProcessingError) as raised:
        await setup.processor.process(event_id)

    assert raised.value.attempts == 1
    stored = billing_harness.billing.events[event_id]
    assert (stored.status, stored.attempts) == (WebhookEventStatus.FAILED, 1)
    assert stored.last_error == "RuntimeError: boom: sensitive customer@example.com 4111111111111111"
    assert setup.savepoints == ["opened", "rolled_back"]
    assert billing_harness.product.id in billing_harness.billing.products
    assert setup.alerts.raised == []


async def test_a_failed_event_succeeds_on_a_later_attempt_and_clears_the_error(billing_harness: BillingHarness) -> None:
    setup = make_processor(billing_harness, Handlers(failures_left=2))
    event_id = await store_event(billing_harness)
    for _ in range(2):
        with pytest.raises(WebhookProcessingError):
            await setup.processor.process(event_id)

    result = await setup.processor.process(event_id)

    assert (result.state, result.attempts) == (ProcessingState.PROCESSED, 3)
    stored = billing_harness.billing.events[event_id]
    assert (stored.status, stored.last_error) == (WebhookEventStatus.PROCESSED, None)
    assert setup.alerts.raised == []


async def test_the_last_allowed_attempt_alerts_and_stops_retrying(billing_harness: BillingHarness) -> None:
    setup = make_processor(billing_harness, Handlers(failures_left=10))
    event_id = await store_event(billing_harness)
    for _ in range(MAX_ATTEMPTS - 1):
        with pytest.raises(WebhookProcessingError):
            await setup.processor.process(event_id)
    assert setup.alerts.raised == []

    result = await setup.processor.process(event_id)

    assert (result.state, result.attempts) == (ProcessingState.FAILED_FINAL, MAX_ATTEMPTS)
    [(code, fields)] = setup.alerts.raised
    assert code == "billing.webhook_failed"
    assert fields["event_id"] == str(event_id)
    assert fields["attempts"] == MAX_ATTEMPTS
    assert billing_harness.billing.events[event_id].status is WebhookEventStatus.FAILED


async def test_a_failure_in_the_surrounding_transaction_is_still_recorded(billing_harness: BillingHarness) -> None:
    calls = 0

    @asynccontextmanager
    async def flaky() -> AsyncGenerator[AsyncSession]:
        nonlocal calls
        calls += 1
        async with billing_harness.world.transaction() as session:
            yield session
            if calls == 1:
                message = "connection lost during commit"
                raise ConnectionError(message)

    setup = make_processor(billing_harness, Handlers(), transaction=flaky)
    event_id = await store_event(billing_harness)

    with pytest.raises(WebhookProcessingError):
        await setup.processor.process(event_id)

    stored = billing_harness.billing.events[event_id]
    assert (stored.status, stored.attempts) == (WebhookEventStatus.FAILED, 1)
    assert stored.last_error == "ConnectionError: connection lost during commit"


async def test_error_text_is_one_bounded_line_without_payload_dumps() -> None:
    long = RuntimeError("first line\n" + "payload " * 1_000)

    described = describe_failure(long)

    assert described == "RuntimeError: first line"
    assert len(describe_failure(RuntimeError("x" * 10_000))) <= 2_000
    assert describe_failure(RuntimeError()) == "RuntimeError"


async def test_validation_errors_are_described_without_the_offending_input() -> None:
    with pytest.raises(ValidationError) as raised:
        RazorpayPayment.model_validate({"id": "pay_1", "amount": "secret-card-4111", "currency": "INR"})

    described = describe_failure(raised.value)

    assert described.startswith("ValidationError: ")
    assert "amount" in described
    assert "4111" not in described


def test_registering_two_handlers_for_one_event_is_refused() -> None:
    registry = HandlerRegistry()
    registry.register_handler("payment.captured", Handlers())

    with pytest.raises(DuplicateHandlerError):
        registry.register_handler("payment.captured", Handlers())

    assert registry.event_types() == {"payment.captured"}
    assert registry.handler_for("payment.failed") is None


def payment_event_payload(payment_entity: dict[str, Any], event: WebhookEventName) -> dict[str, Any]:
    return build_envelope(event, WebhookEntities(payment=payment_entity), created_at=1_760_000_000)


async def stored_payment(harness: BillingHarness, payment_id: str) -> dict[str, Any]:
    entity = await harness.razorpay_store.get(EntityKind.PAYMENT, payment_id)
    assert entity is not None
    return entity


async def stored_event_with(harness: BillingHarness, event: WebhookEventName, payload: dict[str, Any]) -> UUID:
    row = NewWebhookEvent(
        id=new_id(),
        provider="razorpay",
        event_id=f"evt_{new_id().hex}",
        event_type=event.value,
        event_created_at=None,
        payload=payload,
        received_at=harness.clock.now(),
    )
    assert await harness.billing.insert_event(row)
    return row.id


def real_processor(harness: BillingHarness) -> tuple[WebhookProcessor, Alerts]:
    registry = HandlerRegistry()
    PaymentEventHandlers(harness.settlement).register(registry)
    alerts = Alerts()
    return (
        WebhookProcessor(
            harness.world.transaction,
            registry,
            harness.clock,
            lambda: MAX_ATTEMPTS,
            ProcessorPorts(store_factory=harness.billing, savepoint=_noop_savepoint, alert=alerts),
        ),
        alerts,
    )


@asynccontextmanager
async def _noop_savepoint(session: AsyncSession) -> AsyncGenerator[None]:
    del session
    yield


@pytest.mark.parametrize("event", [WebhookEventName.PAYMENT_CAPTURED, WebhookEventName.ORDER_PAID])
async def test_captured_payment_events_settle_the_order(
    billing_harness: BillingHarness, event: WebhookEventName
) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order)
    entity = await stored_payment(billing_harness, payment.id)
    order_entity = await billing_harness.razorpay_store.get(EntityKind.ORDER, order.razorpay_order_id or "")
    envelope = build_envelope(event, WebhookEntities(payment=entity, order=order_entity), created_at=1_760_000_000)
    event_id = await stored_event_with(billing_harness, event, envelope)
    processor, _ = real_processor(billing_harness)

    result = await processor.process(event_id)

    assert result.state is ProcessingState.PROCESSED
    assert billing_harness.billing.orders[order.id].status is OrderStatus.PAID
    assert billing_harness.balance() == PACK_CREDITS


async def test_the_order_paid_event_after_the_captured_event_grants_nothing_more(
    billing_harness: BillingHarness,
) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order)
    entity = await stored_payment(billing_harness, payment.id)
    order_entity = await billing_harness.razorpay_store.get(EntityKind.ORDER, order.razorpay_order_id or "")
    processor, _ = real_processor(billing_harness)
    captured = build_envelope(WebhookEventName.PAYMENT_CAPTURED, WebhookEntities(payment=entity), created_at=1)
    paid = build_envelope(
        WebhookEventName.ORDER_PAID, WebhookEntities(payment=entity, order=order_entity), created_at=2
    )

    await processor.process(await stored_event_with(billing_harness, WebhookEventName.PAYMENT_CAPTURED, captured))
    await processor.process(await stored_event_with(billing_harness, WebhookEventName.ORDER_PAID, paid))

    assert billing_harness.balance() == PACK_CREDITS
    assert len(billing_harness.credits_store.ledger) == 1


async def test_a_failed_payment_event_records_the_attempt_and_keeps_the_order_pending(
    billing_harness: BillingHarness,
) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order, PaymentOutcome.FAILURE)
    entity = await stored_payment(billing_harness, payment.id)
    envelope = payment_event_payload(entity, WebhookEventName.PAYMENT_FAILED)
    processor, _ = real_processor(billing_harness)

    result = await processor.process(
        await stored_event_with(billing_harness, WebhookEventName.PAYMENT_FAILED, envelope)
    )

    assert result.state is ProcessingState.PROCESSED
    assert billing_harness.billing.orders[order.id].status is OrderStatus.PENDING
    [recorded] = billing_harness.billing.payments.values()
    assert recorded.status.value == "failed"


async def test_a_payment_event_for_an_unknown_order_is_ignored_as_an_unknown_entity(
    billing_harness: BillingHarness,
) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order)
    entity = await stored_payment(billing_harness, payment.id)
    entity["order_id"] = "order_not_ours"
    processor, _ = real_processor(billing_harness)
    event_id = await stored_event_with(
        billing_harness,
        WebhookEventName.PAYMENT_CAPTURED,
        payment_event_payload(entity, WebhookEventName.PAYMENT_CAPTURED),
    )

    result = await processor.process(event_id)

    assert result.state is ProcessingState.IGNORED
    stored = billing_harness.billing.events[event_id]
    assert stored.ignored_reason == "unknown_entity"
    assert billing_harness.balance() == 0


async def test_a_payment_event_without_a_payment_entity_is_ignored(billing_harness: BillingHarness) -> None:
    processor, _ = real_processor(billing_harness)
    event_id = await stored_event_with(
        billing_harness, WebhookEventName.PAYMENT_CAPTURED, {"event": "payment.captured", "payload": {}}
    )

    assert (await processor.process(event_id)).state is ProcessingState.IGNORED
    assert billing_harness.billing.events[event_id].ignored_reason == "unknown_entity"


async def test_a_malformed_payment_entity_fails_without_echoing_its_content(billing_harness: BillingHarness) -> None:
    processor, _ = real_processor(billing_harness)
    event_id = await stored_event_with(
        billing_harness,
        WebhookEventName.PAYMENT_CAPTURED,
        {"payload": {"payment": {"entity": {"id": "pay_1", "amount": "not-a-number-4111"}}}},
    )

    with pytest.raises(WebhookProcessingError):
        await processor.process(event_id)

    stored = billing_harness.billing.events[event_id]
    assert stored.status is WebhookEventStatus.FAILED
    assert stored.last_error is not None
    assert "4111" not in stored.last_error


@pytest.mark.parametrize(
    "event",
    [
        WebhookEventName.SUBSCRIPTION_CHARGED,
        WebhookEventName.SUBSCRIPTION_ACTIVATED,
        WebhookEventName.REFUND_PROCESSED,
    ],
)
async def test_subscription_and_refund_events_are_stored_and_ignored_until_their_handlers_exist(
    billing_harness: BillingHarness, event: WebhookEventName
) -> None:
    processor, _ = real_processor(billing_harness)
    event_id = await stored_event_with(billing_harness, event, {"account_id": FAKE_ACCOUNT_ID})

    assert (await processor.process(event_id)).state is ProcessingState.IGNORED
    assert billing_harness.billing.events[event_id].ignored_reason == "unhandled_event"


async def test_the_requeuer_dispatches_every_candidate(billing_harness: BillingHarness) -> None:
    first, second = await store_event(billing_harness), await store_event(billing_harness)
    billing_harness.billing.pending_candidates = [first, second]
    dispatcher = Dispatcher()
    requeuer = WebhookRequeuer(
        billing_harness.world.transaction,
        billing_harness.clock,
        dispatcher,
        RequeuePolicy(lambda: MAX_ATTEMPTS, "motionile:billing.process_webhook_event"),
        store_factory=billing_harness.billing,
    )

    assert await requeuer.requeue_stuck() == 2
    assert dispatcher.calls == [(first, False), (second, False)]


@pytest.mark.parametrize(
    "status", [WebhookEventStatus.FAILED, WebhookEventStatus.PROCESSED, WebhookEventStatus.IGNORED]
)
async def test_admins_can_reprocess_failed_processed_and_ignored_events(
    billing_harness: BillingHarness, status: WebhookEventStatus
) -> None:
    event_id = await store_event(billing_harness)
    billing_harness.billing.events[event_id] = replace(billing_harness.billing.events[event_id], status=status)
    dispatcher = Dispatcher()

    async with billing_harness.world.transaction() as session:
        event = await reprocess_event_with(session, event_id, dispatcher, store_factory=billing_harness.billing)

    assert event.id == event_id
    assert dispatcher.calls == [(event_id, True)]


@pytest.mark.parametrize("status", [WebhookEventStatus.RECEIVED, WebhookEventStatus.PROCESSING])
async def test_events_still_in_flight_cannot_be_reprocessed(
    billing_harness: BillingHarness, status: WebhookEventStatus
) -> None:
    event_id = await store_event(billing_harness)
    billing_harness.billing.events[event_id] = replace(billing_harness.billing.events[event_id], status=status)
    dispatcher = Dispatcher()

    async with billing_harness.world.transaction() as session:
        with pytest.raises(WebhookEventNotReprocessableError):
            await reprocess_event_with(session, event_id, dispatcher, store_factory=billing_harness.billing)

    assert dispatcher.calls == []


async def test_reprocessing_an_unknown_event_is_not_found(billing_harness: BillingHarness) -> None:
    async with billing_harness.world.transaction() as session:
        with pytest.raises(WebhookEventNotFoundError):
            await reprocess_event_with(session, new_id(), Dispatcher(), store_factory=billing_harness.billing)
