from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, status
from pydantic import Field, SecretStr
from starlette.types import ASGIApp

from motionile.core.clock import Clock
from motionile.core.dependencies import ResourcesDep
from motionile.core.errors import ConflictError, NotFoundError, ValidationAppError, problem_responses
from motionile.core.schemas import ResponseModel, StrictModel
from motionile.modules.billing.razorpay.credentials import RazorpayCredentials, razorpay_credentials
from motionile.modules.billing.razorpay.exceptions import RazorpayNotFoundError
from motionile.modules.billing.razorpay.factory import fake_simulator_for, fake_store_for
from motionile.modules.billing.razorpay.fake_delivery import deliver_webhook
from motionile.modules.billing.razorpay.fake_entities import epoch
from motionile.modules.billing.razorpay.fake_events import (
    MissingWebhookEntityError,
    WebhookEventName,
    WebhookReferences,
    build_webhook,
    load_entities,
)
from motionile.modules.billing.razorpay.fake_simulator import (
    FakeRazorpaySimulator,
    FakeRazorpayStateError,
    PaymentOutcome,
    RefundOutcome,
    SubscriptionEvent,
)
from motionile.modules.billing.razorpay.fake_store import FakeRazorpayStore, FaultKind, FaultOperation
from motionile.modules.billing.razorpay.signatures import sign_order_payment, sign_subscription_payment

IDENTIFIER_PATTERN = r"^[A-Za-z0-9_]+$"
INVALID_WEBHOOK_SECRET = SecretStr("motionile-invalid-webhook-secret")
MAX_AMOUNT_PAISE = 100_000_000_00
MAX_DELIVERIES = 20
MAX_WEBHOOKS = 10
MAX_FAULT_COUNT = 100

OrderIdPath = Annotated[str, Path(alias="razorpayOrderId", pattern=IDENTIFIER_PATTERN, max_length=64)]
SubscriptionIdPath = Annotated[str, Path(alias="razorpaySubscriptionId", pattern=IDENTIFIER_PATTERN, max_length=64)]
RefundIdPath = Annotated[str, Path(alias="razorpayRefundId", pattern=IDENTIFIER_PATTERN, max_length=64)]


def require_fake_providers(resources: ResourcesDep) -> None:
    if not resources.settings.is_fake_providers:
        raise NotFoundError


fake_razorpay_router = APIRouter(
    prefix="/razorpay", tags=["test_support"], dependencies=[Depends(require_fake_providers)]
)


@dataclass(frozen=True)
class FakeWorld:
    app: ASGIApp
    store: FakeRazorpayStore
    simulator: FakeRazorpaySimulator
    credentials: RazorpayCredentials
    clock: Clock


def get_fake_world(request: Request, resources: ResourcesDep) -> FakeWorld:
    return FakeWorld(
        app=request.app,
        store=fake_store_for(resources),
        simulator=fake_simulator_for(resources),
        credentials=razorpay_credentials(resources.settings),
        clock=resources.clock,
    )


FakeWorldDep = Annotated[FakeWorld, Depends(get_fake_world)]


class DeliveryOptions(StrictModel):
    event_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    created_at: int | None = Field(default=None, ge=0, le=4_102_444_800)
    repeat: int = Field(default=1, ge=1, le=MAX_DELIVERIES)
    valid_signature: bool = True


class EmittedWebhook(ResponseModel):
    event_id: str
    event: str
    status_codes: list[int]


class StatusResponse(ResponseModel):
    status: str


class PayOrderRequest(StrictModel):
    outcome: PaymentOutcome
    amount_paise: int | None = Field(default=None, ge=1, le=MAX_AMOUNT_PAISE)
    currency: str | None = Field(default=None, min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    method: str = Field(default="card", min_length=1, max_length=20, pattern=r"^[a-z_]+$")
    webhooks: list[WebhookEventName] = Field(default_factory=list[WebhookEventName], max_length=MAX_WEBHOOKS)


class PayOrderResponse(ResponseModel):
    razorpay_order_id: str = Field(alias="razorpay_order_id")
    razorpay_payment_id: str = Field(alias="razorpay_payment_id")
    razorpay_signature: str | None = Field(alias="razorpay_signature")
    payment_status: str
    webhooks: list[EmittedWebhook]


class AuthorizeSubscriptionRequest(StrictModel):
    webhooks: list[WebhookEventName] = Field(default_factory=list[WebhookEventName], max_length=MAX_WEBHOOKS)


class AuthorizeSubscriptionResponse(ResponseModel):
    razorpay_payment_id: str = Field(alias="razorpay_payment_id")
    razorpay_subscription_id: str = Field(alias="razorpay_subscription_id")
    razorpay_signature: str = Field(alias="razorpay_signature")
    subscription_status: str
    webhooks: list[EmittedWebhook]


class TransitionRequest(DeliveryOptions):
    event: SubscriptionEvent
    emit: bool = False


class TransitionResponse(ResponseModel):
    subscription_status: str
    paid_count: int
    razorpay_payment_id: str | None
    webhooks: list[EmittedWebhook]


class SettleRefundRequest(StrictModel):
    outcome: RefundOutcome


class WebhookRequest(DeliveryOptions):
    event: WebhookEventName
    order_id: str | None = Field(default=None, max_length=64, pattern=IDENTIFIER_PATTERN)
    payment_id: str | None = Field(default=None, max_length=64, pattern=IDENTIFIER_PATTERN)
    refund_id: str | None = Field(default=None, max_length=64, pattern=IDENTIFIER_PATTERN)
    subscription_id: str | None = Field(default=None, max_length=64, pattern=IDENTIFIER_PATTERN)


class FaultRequest(StrictModel):
    operation: FaultOperation
    kind: FaultKind
    count: int = Field(default=1, ge=1, le=MAX_FAULT_COUNT)


@contextmanager
def translated_errors() -> Generator[None]:
    try:
        yield
    except RazorpayNotFoundError:
        raise NotFoundError(code="fake_razorpay_not_found") from None
    except FakeRazorpayStateError as error:
        raise ConflictError(str(error), code="fake_razorpay_state_conflict") from None
    except MissingWebhookEntityError as error:
        raise ValidationAppError(str(error), code="fake_razorpay_missing_entity") from None


async def emit_webhook(
    world: FakeWorld, event: WebhookEventName, options: DeliveryOptions, references: WebhookReferences
) -> EmittedWebhook:
    entities = await load_entities(world.store, event, references)
    webhook = build_webhook(
        event,
        entities,
        secret=world.credentials.webhook_secret if options.valid_signature else INVALID_WEBHOOK_SECRET,
        created_at=options.created_at if options.created_at is not None else epoch(world.clock.now()),
        event_id=options.event_id,
    )
    statuses = await deliver_webhook(world.app, webhook, deliveries=options.repeat)
    return EmittedWebhook(event_id=webhook.event_id, event=event.value, status_codes=statuses)


@fake_razorpay_router.post(
    "/orders/{razorpayOrderId}/pay",
    response_model=PayOrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Pay a fake Razorpay order as the customer would",
    responses=problem_responses(status.HTTP_404_NOT_FOUND, status.HTTP_409_CONFLICT),
)
async def fake_razorpay_pay_order(
    razorpay_order_id: OrderIdPath, body: PayOrderRequest, world: FakeWorldDep
) -> PayOrderResponse:
    with translated_errors():
        result = await world.simulator.pay_order(
            razorpay_order_id, body.outcome, amount=body.amount_paise, currency=body.currency, method=body.method
        )
        payment_id: str = result.payment["id"]
        emitted = [
            await emit_webhook(
                world,
                event,
                DeliveryOptions(),
                WebhookReferences(order_id=razorpay_order_id, payment_id=payment_id),
            )
            for event in body.webhooks
        ]
    signature = (
        None
        if body.outcome is PaymentOutcome.FAILURE
        else sign_order_payment(razorpay_order_id, payment_id, world.credentials.key_secret)
    )
    return PayOrderResponse(
        razorpay_order_id=razorpay_order_id,
        razorpay_payment_id=payment_id,
        razorpay_signature=signature,
        payment_status=result.payment["status"],
        webhooks=emitted,
    )


@fake_razorpay_router.post(
    "/subscriptions/{razorpaySubscriptionId}/authorize",
    response_model=AuthorizeSubscriptionResponse,
    status_code=status.HTTP_200_OK,
    summary="Authorize a fake Razorpay subscription mandate as the customer would",
    responses=problem_responses(status.HTTP_404_NOT_FOUND, status.HTTP_409_CONFLICT),
)
async def fake_razorpay_authorize_subscription(
    razorpay_subscription_id: SubscriptionIdPath, body: AuthorizeSubscriptionRequest, world: FakeWorldDep
) -> AuthorizeSubscriptionResponse:
    with translated_errors():
        result = await world.simulator.authorize_subscription(razorpay_subscription_id)
        payment_id: str = result.payment["id"]
        emitted = [
            await emit_webhook(
                world,
                event,
                DeliveryOptions(),
                WebhookReferences(payment_id=payment_id, subscription_id=razorpay_subscription_id),
            )
            for event in body.webhooks
        ]
    return AuthorizeSubscriptionResponse(
        razorpay_payment_id=payment_id,
        razorpay_subscription_id=razorpay_subscription_id,
        razorpay_signature=sign_subscription_payment(
            payment_id, razorpay_subscription_id, world.credentials.key_secret
        ),
        subscription_status=result.subscription["status"],
        webhooks=emitted,
    )


@fake_razorpay_router.post(
    "/subscriptions/{razorpaySubscriptionId}/transition",
    response_model=TransitionResponse,
    status_code=status.HTTP_200_OK,
    summary="Advance a fake Razorpay subscription the way Razorpay would",
    responses=problem_responses(
        status.HTTP_404_NOT_FOUND, status.HTTP_409_CONFLICT, status.HTTP_422_UNPROCESSABLE_CONTENT
    ),
)
async def fake_razorpay_transition_subscription(
    razorpay_subscription_id: SubscriptionIdPath, body: TransitionRequest, world: FakeWorldDep
) -> TransitionResponse:
    with translated_errors():
        result = await world.simulator.transition_subscription(razorpay_subscription_id, body.event)
        payment_id: str | None = result.payment["id"] if result.payment else None
        emitted = (
            [
                await emit_webhook(
                    world,
                    WebhookEventName(f"subscription.{body.event.value}"),
                    body,
                    WebhookReferences(payment_id=payment_id, subscription_id=razorpay_subscription_id),
                )
            ]
            if body.emit
            else []
        )
    return TransitionResponse(
        subscription_status=result.subscription["status"],
        paid_count=result.subscription["paid_count"],
        razorpay_payment_id=payment_id,
        webhooks=emitted,
    )


@fake_razorpay_router.post(
    "/refunds/{razorpayRefundId}/settle",
    response_model=StatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Settle a pending fake Razorpay refund",
    responses=problem_responses(status.HTTP_404_NOT_FOUND, status.HTTP_409_CONFLICT),
)
async def fake_razorpay_settle_refund(
    razorpay_refund_id: RefundIdPath, body: SettleRefundRequest, world: FakeWorldDep
) -> StatusResponse:
    with translated_errors():
        result = await world.simulator.settle_refund(razorpay_refund_id, body.outcome)
    return StatusResponse(status=result.refund["status"])


@fake_razorpay_router.post(
    "/webhooks",
    response_model=EmittedWebhook,
    status_code=status.HTTP_200_OK,
    summary="Build a webhook from the fake Razorpay state and deliver it to this application",
    responses=problem_responses(status.HTTP_404_NOT_FOUND, status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def fake_razorpay_deliver_webhook(body: WebhookRequest, world: FakeWorldDep) -> EmittedWebhook:
    with translated_errors():
        return await emit_webhook(
            world,
            body.event,
            body,
            WebhookReferences(
                order_id=body.order_id,
                payment_id=body.payment_id,
                refund_id=body.refund_id,
                subscription_id=body.subscription_id,
            ),
        )


@fake_razorpay_router.post(
    "/faults",
    response_model=StatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Inject a fault into a fake Razorpay operation",
)
async def fake_razorpay_inject_fault(body: FaultRequest, world: FakeWorldDep) -> StatusResponse:
    await world.store.add_fault(body.operation, body.kind, body.count)
    return StatusResponse(status="armed")


@fake_razorpay_router.post(
    "/reset",
    response_model=StatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Erase every fake Razorpay entity and fault",
)
async def fake_razorpay_reset(world: FakeWorldDep) -> StatusResponse:
    await world.store.reset()
    return StatusResponse(status="reset")
