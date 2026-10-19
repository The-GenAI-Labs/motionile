import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import orjson
from pydantic import SecretStr, ValidationError

from motionile.core.clock import Clock
from motionile.core.errors import ServiceUnavailableError
from motionile.core.ids import new_id
from motionile.modules.billing.exceptions import (
    InvalidWebhookPayloadError,
    InvalidWebhookSignatureError,
    WebhookEventIdMissingError,
    WebhookTooLargeError,
)
from motionile.modules.billing.ports import EventDispatcher, StoreFactory, Transaction
from motionile.modules.billing.razorpay.exceptions import RazorpayNotConfiguredError
from motionile.modules.billing.razorpay.signatures import verify_webhook_signature
from motionile.modules.billing.records import NewWebhookEvent
from motionile.modules.billing.repository import SqlBillingRepository
from motionile.modules.billing.schemas import WebhookEnvelope, WebhookReceiptStatus
from motionile.modules.billing.states import WebhookEventStatus

PROVIDER = "razorpay"
MAX_BODY_BYTES = 262_144
EVENT_ID_PATTERN = re.compile(r"^[\x21-\x7E]{1,128}$")
REQUEUE_DUPLICATE_AFTER = timedelta(seconds=60)

type SecretSource = Callable[[], SecretStr]


def event_time(epoch_seconds: int | None) -> datetime | None:
    if epoch_seconds is None:
        return None
    try:
        return datetime.fromtimestamp(epoch_seconds, UTC)
    except (OverflowError, OSError, ValueError):
        return None


def parse_envelope(raw_body: bytes) -> tuple[WebhookEnvelope, dict[str, Any]]:
    try:
        data: object = orjson.loads(raw_body)
    except orjson.JSONDecodeError as error:
        raise InvalidWebhookPayloadError("The webhook body is not valid JSON.") from error
    if not isinstance(data, dict):
        raise InvalidWebhookPayloadError("The webhook body must be a JSON object.")
    body = cast("dict[str, Any]", data)
    try:
        envelope = WebhookEnvelope.model_validate(body)
    except ValidationError as error:
        raise InvalidWebhookPayloadError("The webhook body is missing required fields.") from error
    return envelope, body


class WebhookReceiver:
    def __init__(
        self,
        transaction: Transaction,
        clock: Clock,
        webhook_secret: SecretSource,
        dispatch: EventDispatcher,
        *,
        store_factory: StoreFactory = SqlBillingRepository,
    ) -> None:
        self._transaction = transaction
        self._clock = clock
        self._webhook_secret = webhook_secret
        self._dispatch = dispatch
        self._store_factory = store_factory

    async def receive(self, raw_body: bytes, signature: str | None, event_id: str | None) -> WebhookReceiptStatus:
        if len(raw_body) > MAX_BODY_BYTES:
            raise WebhookTooLargeError
        self._require_signature(raw_body, signature)
        envelope, payload = parse_envelope(raw_body)
        if event_id is None or EVENT_ID_PATTERN.fullmatch(event_id) is None:
            raise WebhookEventIdMissingError("Send the provider event id in X-Razorpay-Event-Id.")
        now = self._clock.now()
        async with self._transaction() as session:
            store = self._store_factory(session)
            event = NewWebhookEvent(
                id=new_id(),
                provider=PROVIDER,
                event_id=event_id,
                event_type=envelope.event,
                event_created_at=event_time(envelope.created_at),
                payload=payload,
                received_at=now,
            )
            if await store.insert_event(event):
                self._dispatch(session, event.id, False)
                return "received"
            existing = await store.event_by_provider_id(PROVIDER, event_id)
            if (
                existing is not None
                and existing.status is WebhookEventStatus.RECEIVED
                and now - existing.received_at > REQUEUE_DUPLICATE_AFTER
            ):
                self._dispatch(session, existing.id, False)
        return "duplicate"

    def _require_signature(self, raw_body: bytes, signature: str | None) -> None:
        try:
            secret = self._webhook_secret()
        except RazorpayNotConfiguredError as error:
            raise ServiceUnavailableError(
                "Webhook verification is not configured.", code="webhook_not_configured"
            ) from error
        if signature is None or not verify_webhook_signature(raw_body, signature, secret):
            raise InvalidWebhookSignatureError
