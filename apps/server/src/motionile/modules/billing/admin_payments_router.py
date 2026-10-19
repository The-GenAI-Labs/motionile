from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from motionile.modules.access import BillingReadDep
from motionile.modules.billing.admin_records import OrderFilter, PaymentFilter, RefundFilter
from motionile.modules.billing.admin_responses import DETAIL_ERRORS, LIST_ERRORS
from motionile.modules.billing.admin_schemas import (
    AdminOrderDetailResponse,
    AdminOrderPageResponse,
    AdminPaymentDetailResponse,
    AdminPaymentPageResponse,
    AdminRefundPageResponse,
    AdminRefundResponse,
    ClawbackPreviewQuery,
    OrderListQuery,
    PaymentListQuery,
    RefundListQuery,
)
from motionile.modules.billing.admin_views import (
    order_detail_response,
    order_response,
    payment_detail_response,
    payment_response,
    refund_response,
)
from motionile.modules.billing.dependencies import BillingServicesDep
from motionile.modules.billing.states import OrderStatus, PaymentRecordStatus, RefundStatus

payments_router = APIRouter()


@payments_router.get(
    "/payments",
    response_model=AdminPaymentPageResponse,
    status_code=status.HTTP_200_OK,
    summary="List payments, newest first",
    responses=LIST_ERRORS,
)
async def list_payments(
    query: Annotated[PaymentListQuery, Query()], _: BillingReadDep, services: BillingServicesDep
) -> AdminPaymentPageResponse:
    page = await services.admin.payments.list_payments(
        PaymentFilter(
            status=PaymentRecordStatus(query.status) if query.status is not None else None,
            user_id=query.user_id,
            order_id=query.order_id,
            created_from=query.created_from,
            created_to=query.created_to,
            flagged=query.flagged,
        ),
        query.cursor,
        query.limit,
    )
    return AdminPaymentPageResponse(items=[payment_response(row) for row in page.items], next_cursor=page.next_cursor)


@payments_router.get(
    "/payments/{payment_id}",
    response_model=AdminPaymentDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a payment with its order, refunds, credit lot and a clawback preview",
    responses=DETAIL_ERRORS,
)
async def get_payment(
    payment_id: UUID,
    query: Annotated[ClawbackPreviewQuery, Query()],
    _: BillingReadDep,
    services: BillingServicesDep,
) -> AdminPaymentDetailResponse:
    return payment_detail_response(await services.admin.payments.payment(payment_id, query.amount_paise))


@payments_router.get(
    "/orders",
    response_model=AdminOrderPageResponse,
    status_code=status.HTTP_200_OK,
    summary="List orders, newest first, optionally only flagged ones",
    responses=LIST_ERRORS,
)
async def list_orders(
    query: Annotated[OrderListQuery, Query()], _: BillingReadDep, services: BillingServicesDep
) -> AdminOrderPageResponse:
    page = await services.admin.payments.list_orders(
        OrderFilter(
            status=OrderStatus(query.status) if query.status is not None else None,
            flagged=query.flagged,
            user_id=query.user_id,
        ),
        query.cursor,
        query.limit,
    )
    return AdminOrderPageResponse(items=[order_response(row) for row in page.items], next_cursor=page.next_cursor)


@payments_router.get(
    "/orders/{order_id}",
    response_model=AdminOrderDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get an order with its payments",
    responses=DETAIL_ERRORS,
)
async def get_order(order_id: UUID, _: BillingReadDep, services: BillingServicesDep) -> AdminOrderDetailResponse:
    row, payments = await services.admin.payments.order(order_id)
    return order_detail_response(row, payments)


@payments_router.get(
    "/refunds",
    response_model=AdminRefundPageResponse,
    status_code=status.HTTP_200_OK,
    summary="List refunds, newest first",
    responses=LIST_ERRORS,
)
async def list_refunds(
    query: Annotated[RefundListQuery, Query()], _: BillingReadDep, services: BillingServicesDep
) -> AdminRefundPageResponse:
    page = await services.admin.payments.list_refunds(
        RefundFilter(
            status=RefundStatus(query.status) if query.status is not None else None, payment_id=query.payment_id
        ),
        query.cursor,
        query.limit,
    )
    return AdminRefundPageResponse(items=[refund_response(row) for row in page.items], next_cursor=page.next_cursor)


@payments_router.get(
    "/refunds/{refund_id}",
    response_model=AdminRefundResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a refund",
    responses=DETAIL_ERRORS,
)
async def get_refund(refund_id: UUID, _: BillingReadDep, services: BillingServicesDep) -> AdminRefundResponse:
    return refund_response(await services.admin.payments.refund(refund_id))
