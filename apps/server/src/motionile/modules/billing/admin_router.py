from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from motionile.core.errors import problem_responses
from motionile.core.idempotency import IdempotencyGuard, idempotent, read_key
from motionile.core.ratelimit.limiter import rate_limit
from motionile.modules.access import BillingRefundsCreateDep
from motionile.modules.auth import enforce_csrf
from motionile.modules.billing.admin_credits_router import credits_router
from motionile.modules.billing.admin_payments_router import payments_router
from motionile.modules.billing.admin_products_router import products_router
from motionile.modules.billing.admin_reports_router import reports_router
from motionile.modules.billing.admin_subscriptions_router import subscriptions_router
from motionile.modules.billing.admin_webhooks_router import webhooks_router
from motionile.modules.billing.dependencies import BillingServicesDep
from motionile.modules.billing.schemas import CreateRefundRequest, RefundResponse
from motionile.modules.billing.services.refunds import CreateRefundCommand

REFUND_SCOPE = "billing.refund.create"

billing_admin_router = APIRouter(
    prefix="/admin/billing",
    tags=["admin-billing"],
    dependencies=[Depends(enforce_csrf), Depends(rate_limit("api.default"))],
    responses=problem_responses(401, 403, 404, 409, 422, 502, 503),
)
for child in (
    products_router,
    payments_router,
    subscriptions_router,
    webhooks_router,
    credits_router,
    reports_router,
):
    billing_admin_router.include_router(child)


@dataclass(frozen=True)
class RefundContext:
    admin_id: UUID | None
    request_key: str


def get_refund_context(request: Request, principal: BillingRefundsCreateDep) -> RefundContext:
    return RefundContext(principal.user_id, read_key(request))


RefundContextDep = Annotated[RefundContext, Depends(get_refund_context)]


@billing_admin_router.post(
    "/payments/{payment_id}/refunds",
    response_model=RefundResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Refund a captured payment in full or in part",
)
async def create_refund(
    payment_id: UUID,
    body: CreateRefundRequest,
    context: RefundContextDep,
    services: BillingServicesDep,
    guard: Annotated[IdempotencyGuard, Depends(idempotent(REFUND_SCOPE))],
) -> JSONResponse:
    refund = await services.refunds.create(
        CreateRefundCommand(
            admin_id=context.admin_id,
            payment_id=payment_id,
            amount_paise=body.amount_paise,
            reason=body.reason,
            request_key=context.request_key,
        )
    )
    return await guard.respond(
        RefundResponse.model_validate(
            {
                "id": refund.id,
                "status": refund.status.value,
                "amount_paise": refund.amount_paise,
                "reason": refund.reason,
                "credits_clawed_back": refund.credits_clawed_back,
                "razorpay_refund_id": refund.razorpay_refund_id,
                "created_at": refund.created_at,
            }
        ),
        status_code=status.HTTP_201_CREATED,
    )
