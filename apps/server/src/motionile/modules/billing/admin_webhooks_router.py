from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from motionile.modules.access import BillingWebhooksManageDep
from motionile.modules.billing.admin_records import EventFilter
from motionile.modules.billing.admin_responses import DETAIL_ERRORS, LIST_ERRORS, WRITE_ERRORS
from motionile.modules.billing.admin_schemas import (
    AdminWebhookEventDetailResponse,
    AdminWebhookEventPageResponse,
    WebhookListQuery,
    WebhookReprocessResponse,
)
from motionile.modules.billing.admin_views import (
    actor_of,
    event_detail_response,
    event_response,
    reprocess_response,
)
from motionile.modules.billing.dependencies import BillingServicesDep
from motionile.modules.billing.states import WebhookEventStatus

webhooks_router = APIRouter()


@webhooks_router.get(
    "/webhooks",
    response_model=AdminWebhookEventPageResponse,
    status_code=status.HTTP_200_OK,
    summary="List stored webhook events without their payloads",
    responses=LIST_ERRORS,
)
async def list_webhook_events(
    query: Annotated[WebhookListQuery, Query()], _: BillingWebhooksManageDep, services: BillingServicesDep
) -> AdminWebhookEventPageResponse:
    page = await services.admin.webhooks.list(
        EventFilter(
            status=WebhookEventStatus(query.status) if query.status is not None else None,
            event_type=query.event_type,
            received_from=query.received_from,
            received_to=query.received_to,
        ),
        query.cursor,
        query.limit,
    )
    return AdminWebhookEventPageResponse(
        items=[event_response(event) for event in page.items], next_cursor=page.next_cursor
    )


@webhooks_router.get(
    "/webhooks/{event_row_id}",
    response_model=AdminWebhookEventDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a stored webhook event with its payload",
    responses=DETAIL_ERRORS,
)
async def get_webhook_event(
    event_row_id: UUID, _: BillingWebhooksManageDep, services: BillingServicesDep
) -> AdminWebhookEventDetailResponse:
    return event_detail_response(await services.admin.webhooks.get(event_row_id))


@webhooks_router.post(
    "/webhooks/{event_row_id}/reprocess",
    response_model=WebhookReprocessResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a stored webhook event for forced reprocessing",
    responses=WRITE_ERRORS,
)
async def reprocess_webhook_event(
    event_row_id: UUID, principal: BillingWebhooksManageDep, services: BillingServicesDep
) -> WebhookReprocessResponse:
    return reprocess_response(await services.admin.webhooks.reprocess(actor_of(principal), event_row_id))
