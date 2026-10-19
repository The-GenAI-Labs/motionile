from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status
from fastapi.responses import StreamingResponse

from motionile.modules.access import BillingReadDep
from motionile.modules.billing.admin_credit_schemas import (
    AnalyticsQuery,
    CreditsAnalyticsResponse,
    RevenueAnalyticsResponse,
    SubscriptionAnalyticsResponse,
)
from motionile.modules.billing.admin_records import RunFilter
from motionile.modules.billing.admin_responses import DETAIL_ERRORS, LIST_ERRORS
from motionile.modules.billing.admin_schemas import AdminRunPageResponse, AdminRunResponse, RunListQuery
from motionile.modules.billing.admin_views import (
    credits_analytics_response,
    revenue_response,
    run_response,
    subscription_analytics_response,
)
from motionile.modules.billing.dependencies import BillingServicesDep
from motionile.modules.billing.states import RunStatus

reports_router = APIRouter()

REPORT_RESPONSES = {
    **DETAIL_ERRORS,
    status.HTTP_200_OK: {
        "description": "The stored JSON report as an attachment",
        "content": {"application/json": {"schema": {"type": "string", "format": "binary"}}},
    },
}


@reports_router.get(
    "/reconciliation/runs",
    response_model=AdminRunPageResponse,
    status_code=status.HTTP_200_OK,
    summary="List reconciliation runs, newest first",
    responses=LIST_ERRORS,
)
async def list_reconciliation_runs(
    query: Annotated[RunListQuery, Query()], _: BillingReadDep, services: BillingServicesDep
) -> AdminRunPageResponse:
    page = await services.admin.reconciliation.list(
        RunFilter(
            type=query.type,
            status=RunStatus(query.status) if query.status is not None else None,
            has_mismatches=query.has_mismatches,
        ),
        query.cursor,
        query.limit,
    )
    return AdminRunPageResponse(items=[run_response(run) for run in page.items], next_cursor=page.next_cursor)


@reports_router.get(
    "/reconciliation/runs/{run_id}",
    response_model=AdminRunResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a reconciliation run",
    responses=DETAIL_ERRORS,
)
async def get_reconciliation_run(run_id: UUID, _: BillingReadDep, services: BillingServicesDep) -> AdminRunResponse:
    return run_response(await services.admin.reconciliation.get(run_id))


@reports_router.get(
    "/reconciliation/runs/{run_id}/report",
    response_model=None,
    response_class=StreamingResponse,
    status_code=status.HTTP_200_OK,
    summary="Download the stored JSON report of a reconciliation run",
    responses=REPORT_RESPONSES,
)
async def download_reconciliation_report(
    run_id: UUID, _: BillingReadDep, services: BillingServicesDep
) -> StreamingResponse:
    download = await services.admin.reconciliation.report(run_id)
    return StreamingResponse(
        download.chunks,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{download.filename}"',
            "Content-Length": str(download.size_bytes),
            "Cache-Control": "no-store",
        },
    )


@reports_router.get(
    "/analytics/revenue",
    response_model=RevenueAnalyticsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get captured, refunded and net revenue per UTC day",
    responses=LIST_ERRORS,
)
async def get_revenue_analytics(
    query: Annotated[AnalyticsQuery, Query()], _: BillingReadDep, services: BillingServicesDep
) -> RevenueAnalyticsResponse:
    return revenue_response(await services.admin.analytics.revenue(query.range_start, query.range_end))


@reports_router.get(
    "/analytics/subscriptions",
    response_model=SubscriptionAnalyticsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get live subscriptions by plan and counts by status",
    responses=LIST_ERRORS,
)
async def get_subscription_analytics(_: BillingReadDep, services: BillingServicesDep) -> SubscriptionAnalyticsResponse:
    return subscription_analytics_response(await services.admin.analytics.subscriptions())


@reports_router.get(
    "/analytics/credits",
    response_model=CreditsAnalyticsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get credits granted, consumed, expired and clawed back per UTC day",
    responses=LIST_ERRORS,
)
async def get_credits_analytics(
    query: Annotated[AnalyticsQuery, Query()], _: BillingReadDep, services: BillingServicesDep
) -> CreditsAnalyticsResponse:
    return credits_analytics_response(await services.admin.analytics.credits(query.range_start, query.range_end))
