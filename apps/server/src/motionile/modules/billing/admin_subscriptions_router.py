from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from motionile.modules.access import BillingReadDep, BillingRefundsCreateDep
from motionile.modules.billing.admin_records import SubscriptionFilter
from motionile.modules.billing.admin_responses import DETAIL_ERRORS, LIST_ERRORS, PROVIDER_ERRORS
from motionile.modules.billing.admin_schemas import (
    AdminSubscriptionCancelRequest,
    AdminSubscriptionDetailResponse,
    AdminSubscriptionPageResponse,
    SubscriptionListQuery,
)
from motionile.modules.billing.admin_views import actor_of, subscription_detail_response, subscription_response
from motionile.modules.billing.dependencies import BillingServicesDep
from motionile.modules.billing.services.subscription_management import AdminCancelCommand
from motionile.modules.billing.states import SubscriptionStatus

subscriptions_router = APIRouter()


@subscriptions_router.get(
    "/subscriptions",
    response_model=AdminSubscriptionPageResponse,
    status_code=status.HTTP_200_OK,
    summary="List subscriptions, newest first",
    responses=LIST_ERRORS,
)
async def list_subscriptions(
    query: Annotated[SubscriptionListQuery, Query()], _: BillingReadDep, services: BillingServicesDep
) -> AdminSubscriptionPageResponse:
    page = await services.admin.subscriptions.list(
        SubscriptionFilter(
            status=SubscriptionStatus(query.status) if query.status is not None else None,
            product_id=query.product_id,
            plan_key=query.plan_key,
            user_id=query.user_id,
        ),
        query.cursor,
        query.limit,
    )
    return AdminSubscriptionPageResponse(
        items=[subscription_response(row) for row in page.items], next_cursor=page.next_cursor
    )


@subscriptions_router.get(
    "/subscriptions/{subscription_id}",
    response_model=AdminSubscriptionDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a subscription with its payments and orders",
    responses=DETAIL_ERRORS,
)
async def get_subscription(
    subscription_id: UUID, _: BillingReadDep, services: BillingServicesDep
) -> AdminSubscriptionDetailResponse:
    return subscription_detail_response(await services.admin.subscriptions.get(subscription_id))


@subscriptions_router.post(
    "/subscriptions/{subscription_id}/cancel",
    response_model=AdminSubscriptionDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel a subscription at the period end or immediately, without refunding",
    responses=PROVIDER_ERRORS,
)
async def cancel_subscription(
    subscription_id: UUID,
    body: AdminSubscriptionCancelRequest,
    principal: BillingRefundsCreateDep,
    services: BillingServicesDep,
) -> AdminSubscriptionDetailResponse:
    detail = await services.admin.subscriptions.cancel(
        AdminCancelCommand(admin_id=actor_of(principal), subscription_id=subscription_id, immediately=body.immediately)
    )
    return subscription_detail_response(detail)
