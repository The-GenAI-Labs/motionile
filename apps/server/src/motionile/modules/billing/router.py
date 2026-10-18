from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse

from motionile.core.errors import problem_responses
from motionile.core.idempotency import IdempotencyGuard, idempotent, read_key
from motionile.core.ratelimit.limiter import rate_limit
from motionile.core.schemas import PageQuery
from motionile.modules.auth import enforce_csrf
from motionile.modules.billing.dependencies import BillingServicesDep, CurrentUserIdDep
from motionile.modules.billing.schemas import (
    ChangeSubscriptionRequest,
    CheckoutResponse,
    CreateOrderRequest,
    CreateSubscriptionRequest,
    CurrentSubscriptionResponse,
    HistoryPageResponse,
    OrderResponse,
    ProductsResponse,
    SubscriptionCheckoutResponse,
    SubscriptionResponse,
    VerifyPaymentRequest,
    VerifyPaymentResponse,
    VerifySubscriptionRequest,
)
from motionile.modules.billing.services.products import CACHE_CONTROL, etag_matches
from motionile.modules.billing.services.subscription_management import VerifySubscriptionCommand
from motionile.modules.billing.services.subscription_views import current_response, subscription_response
from motionile.modules.billing.services.verification import VerifyCommand

ORDER_SCOPE = "billing.order.create"
VERIFY_SCOPE = "billing.payment.verify"
SUBSCRIPTION_SCOPE = "billing.subscription.create"
SUBSCRIPTION_VERIFY_SCOPE = "billing.subscription.verify"

billing_router = APIRouter(
    prefix="/billing",
    tags=["billing"],
    dependencies=[Depends(enforce_csrf)],
)


@billing_router.get(
    "/products",
    response_model=ProductsResponse,
    status_code=status.HTTP_200_OK,
    summary="List the active credit packs and subscription plans",
    dependencies=[Depends(rate_limit("catalog.read"))],
    responses={status.HTTP_304_NOT_MODIFIED: {"description": "Not Modified"}},
)
async def list_products(request: Request, services: BillingServicesDep) -> Response:
    listing = await services.products.listing()
    headers = {"ETag": listing.etag, "Cache-Control": CACHE_CONTROL}
    if etag_matches(request.headers.get("if-none-match"), listing.etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(content=listing.body, media_type="application/json", headers=headers)


@billing_router.post(
    "/orders",
    response_model=CheckoutResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a credit pack order and return the checkout data",
    dependencies=[Depends(rate_limit("billing.order.create"))],
    responses=problem_responses(
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_409_CONFLICT,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        status.HTTP_502_BAD_GATEWAY,
    ),
)
async def create_order(
    body: CreateOrderRequest,
    request: Request,
    user_id: CurrentUserIdDep,
    services: BillingServicesDep,
    guard: Annotated[IdempotencyGuard, Depends(idempotent(ORDER_SCOPE))],
) -> JSONResponse:
    checkout = await services.orders.create(user_id, body.product_code, read_key(request))
    return await guard.respond(
        checkout,
        status_code=status.HTTP_201_CREATED,
        headers={"Location": f"/v1/billing/orders/{checkout.order_id}"},
    )


@billing_router.get(
    "/orders/{order_id}",
    response_model=OrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Get one of your orders",
    dependencies=[Depends(rate_limit("api.default"))],
    responses=problem_responses(status.HTTP_401_UNAUTHORIZED, status.HTTP_404_NOT_FOUND),
)
async def get_order(order_id: UUID, user_id: CurrentUserIdDep, services: BillingServicesDep) -> OrderResponse:
    view = await services.orders.get(user_id, order_id)
    order = view.order
    return OrderResponse.model_validate(
        {
            "id": order.id,
            "status": order.status.value,
            "kind": order.kind,
            "product_code": view.product_code,
            "product_name": view.product_name,
            "amount_paise": order.amount_paise,
            "currency": order.currency,
            "credits_granted": order.credits_granted,
            "paid_at": order.paid_at,
            "expires_at": order.expires_at,
            "failure_reason": order.failure_reason,
        }
    )


@billing_router.post(
    "/payments/verify",
    response_model=VerifyPaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify a checkout payment and settle the order",
    dependencies=[Depends(rate_limit("api.default"))],
    responses=problem_responses(
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_409_CONFLICT,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        status.HTTP_502_BAD_GATEWAY,
    ),
)
async def verify_payment(
    body: VerifyPaymentRequest,
    user_id: CurrentUserIdDep,
    services: BillingServicesDep,
    guard: Annotated[IdempotencyGuard, Depends(idempotent(VERIFY_SCOPE))],
) -> JSONResponse:
    result = await services.verification.verify(
        user_id,
        VerifyCommand(body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature),
    )
    return await guard.respond(
        VerifyPaymentResponse(order_id=result.order_id, status=result.status, credits_granted=result.credits_granted)
    )


@billing_router.get(
    "/history",
    response_model=HistoryPageResponse,
    status_code=status.HTTP_200_OK,
    summary="List your orders, payments and refunds, newest first",
    dependencies=[Depends(rate_limit("api.default"))],
    responses=problem_responses(status.HTTP_401_UNAUTHORIZED, status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def list_history(
    query: Annotated[PageQuery, Query()], user_id: CurrentUserIdDep, services: BillingServicesDep
) -> HistoryPageResponse:
    return await services.history.page(user_id, query.cursor, query.limit)


@billing_router.post(
    "/subscriptions",
    response_model=SubscriptionCheckoutResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a subscription and return the checkout data",
    dependencies=[Depends(rate_limit("billing.order.create"))],
    responses=problem_responses(
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_409_CONFLICT,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        status.HTTP_502_BAD_GATEWAY,
        status.HTTP_503_SERVICE_UNAVAILABLE,
    ),
)
async def create_subscription(
    body: CreateSubscriptionRequest,
    request: Request,
    user_id: CurrentUserIdDep,
    services: BillingServicesDep,
    guard: Annotated[IdempotencyGuard, Depends(idempotent(SUBSCRIPTION_SCOPE))],
) -> JSONResponse:
    checkout = await services.subscriptions.checkout.create(user_id, body.product_code, read_key(request))
    return await guard.respond(checkout, status_code=status.HTTP_201_CREATED)


@billing_router.post(
    "/subscriptions/verify",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify the subscription authorization payment",
    dependencies=[Depends(rate_limit("api.default"))],
    responses=problem_responses(
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_409_CONFLICT,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        status.HTTP_502_BAD_GATEWAY,
        status.HTTP_503_SERVICE_UNAVAILABLE,
    ),
)
async def verify_subscription(
    body: VerifySubscriptionRequest,
    user_id: CurrentUserIdDep,
    services: BillingServicesDep,
    guard: Annotated[IdempotencyGuard, Depends(idempotent(SUBSCRIPTION_VERIFY_SCOPE))],
) -> JSONResponse:
    view = await services.subscriptions.management.verify(
        user_id,
        VerifySubscriptionCommand(body.razorpay_payment_id, body.razorpay_subscription_id, body.razorpay_signature),
    )
    return await guard.respond(subscription_response(view))


@billing_router.get(
    "/subscription",
    response_model=CurrentSubscriptionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get your current subscription",
    dependencies=[Depends(rate_limit("api.default"))],
    responses=problem_responses(status.HTTP_401_UNAUTHORIZED),
)
async def get_subscription(user_id: CurrentUserIdDep, services: BillingServicesDep) -> CurrentSubscriptionResponse:
    return current_response(await services.subscriptions.management.current(user_id))


@billing_router.post(
    "/subscription/cancel",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel your subscription at the end of the billing period",
    dependencies=[Depends(rate_limit("api.default"))],
    responses=problem_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        status.HTTP_502_BAD_GATEWAY,
        status.HTTP_503_SERVICE_UNAVAILABLE,
    ),
)
async def cancel_subscription(user_id: CurrentUserIdDep, services: BillingServicesDep) -> SubscriptionResponse:
    return subscription_response(await services.subscriptions.management.cancel(user_id))


@billing_router.post(
    "/subscription/change",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_200_OK,
    summary="Switch your subscription to another plan from the next billing period",
    dependencies=[Depends(rate_limit("api.default"))],
    responses=problem_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_409_CONFLICT,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        status.HTTP_502_BAD_GATEWAY,
        status.HTTP_503_SERVICE_UNAVAILABLE,
    ),
)
async def change_subscription(
    body: ChangeSubscriptionRequest, user_id: CurrentUserIdDep, services: BillingServicesDep
) -> SubscriptionResponse:
    return subscription_response(await services.subscriptions.management.change(user_id, body.product_code))
