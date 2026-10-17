from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status

from motionile.core.errors import problem_responses
from motionile.core.ratelimit.limiter import rate_limit
from motionile.modules.billing.dependencies import BillingServicesDep
from motionile.modules.billing.schemas import WebhookReceiptResponse

SIGNATURE_HEADER = "X-Razorpay-Signature"
EVENT_ID_HEADER = "X-Razorpay-Event-Id"

webhook_router = APIRouter(
    prefix="/webhooks",
    tags=["webhooks"],
    dependencies=[Depends(rate_limit("webhooks.razorpay"))],
)


@webhook_router.post(
    "/razorpay",
    response_model=WebhookReceiptResponse,
    status_code=status.HTTP_200_OK,
    summary="Receive a signed Razorpay webhook",
    responses=problem_responses(
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_413_CONTENT_TOO_LARGE,
    ),
)
async def receive_razorpay_webhook(
    request: Request,
    services: BillingServicesDep,
    signature: Annotated[str | None, Header(alias=SIGNATURE_HEADER, max_length=256)] = None,
    event_id: Annotated[str | None, Header(alias=EVENT_ID_HEADER, max_length=256)] = None,
) -> WebhookReceiptResponse:
    raw_body = await request.body()
    return WebhookReceiptResponse(status=await services.receiver.receive(raw_body, signature, event_id))
