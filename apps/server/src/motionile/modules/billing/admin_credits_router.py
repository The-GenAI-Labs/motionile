from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse

from motionile.core.idempotency import IdempotencyGuard, idempotent
from motionile.core.schemas import PageQuery
from motionile.modules.access import BillingCreditsAdjustDep, BillingReadDep
from motionile.modules.billing.admin_credit_schemas import (
    AdjustCreditsRequest,
    AdjustCreditsResponse,
    AdminLedgerPageResponse,
    AdminUserCreditsResponse,
)
from motionile.modules.billing.admin_responses import DETAIL_ERRORS, WRITE_ERRORS
from motionile.modules.billing.admin_views import actor_of, ledger_response, user_credits_response
from motionile.modules.billing.dependencies import BillingServicesDep
from motionile.modules.billing.services.admin_credits import AdminAdjustCommand

ADJUST_SCOPE = "billing.credits.adjust"

credits_router = APIRouter()


@credits_router.get(
    "/users/{user_id}/credits",
    response_model=AdminUserCreditsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a user's wallet and credit lots",
    responses=DETAIL_ERRORS,
)
async def get_user_credits(
    user_id: UUID, query: Annotated[PageQuery, Query()], _: BillingReadDep, services: BillingServicesDep
) -> AdminUserCreditsResponse:
    return user_credits_response(await services.admin.credits.wallet(user_id, query.cursor, query.limit))


@credits_router.get(
    "/users/{user_id}/credits/ledger",
    response_model=AdminLedgerPageResponse,
    status_code=status.HTTP_200_OK,
    summary="List a user's credit ledger, newest first",
    responses=DETAIL_ERRORS,
)
async def list_user_credit_ledger(
    user_id: UUID, query: Annotated[PageQuery, Query()], _: BillingReadDep, services: BillingServicesDep
) -> AdminLedgerPageResponse:
    page = await services.admin.credits.ledger(user_id, query.cursor, query.limit)
    return AdminLedgerPageResponse(items=[ledger_response(entry) for entry in page.items], next_cursor=page.next_cursor)


@credits_router.post(
    "/users/{user_id}/credits/adjust",
    response_model=AdjustCreditsResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Grant or remove credits for a user",
    responses=WRITE_ERRORS,
)
async def adjust_user_credits(
    user_id: UUID,
    body: AdjustCreditsRequest,
    principal: BillingCreditsAdjustDep,
    services: BillingServicesDep,
    guard: Annotated[IdempotencyGuard, Depends(idempotent(ADJUST_SCOPE))],
) -> JSONResponse:
    result = await services.admin.credits.adjust(
        AdminAdjustCommand(
            admin_id=actor_of(principal),
            user_id=user_id,
            delta=body.delta,
            reason=body.reason,
            key=guard.key,
            expires_at=body.expires_at,
        )
    )
    return await guard.respond(
        AdjustCreditsResponse(
            user_id=result.user_id,
            delta=result.delta,
            action_id=result.action_id,
            lot_id=result.lot_id,
            balance_after=result.balance_after,
        ),
        status_code=status.HTTP_201_CREATED,
    )
