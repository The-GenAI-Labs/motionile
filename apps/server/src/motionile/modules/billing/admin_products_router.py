from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from motionile.modules.access import BillingProductsManageDep, BillingReadDep
from motionile.modules.billing.admin_records import ProductFilter
from motionile.modules.billing.admin_responses import DETAIL_ERRORS, LIST_ERRORS, PROVIDER_ERRORS, WRITE_ERRORS
from motionile.modules.billing.admin_schemas import (
    AdminProductDetailResponse,
    AdminProductPageResponse,
    CreateProductRequest,
    DuplicateProductRequest,
    ProductListQuery,
    UpdateProductRequest,
)
from motionile.modules.billing.admin_views import actor_of, product_detail_response, product_response
from motionile.modules.billing.dependencies import BillingServicesDep
from motionile.modules.billing.services.admin_products import (
    CreateProductCommand,
    DuplicateProductCommand,
    UpdateProductCommand,
)

products_router = APIRouter()


@products_router.get(
    "/products",
    response_model=AdminProductPageResponse,
    status_code=status.HTTP_200_OK,
    summary="List products with their usage state",
    responses=LIST_ERRORS,
)
async def list_products(
    query: Annotated[ProductListQuery, Query()], _: BillingReadDep, services: BillingServicesDep
) -> AdminProductPageResponse:
    page = await services.admin.products.list(
        ProductFilter(kind=query.kind, is_active=query.is_active, is_sample=query.is_sample, search=query.search),
        query.cursor,
        query.limit,
    )
    return AdminProductPageResponse(items=[product_response(row) for row in page.items], next_cursor=page.next_cursor)


@products_router.get(
    "/products/{product_id}",
    response_model=AdminProductDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a product with its version links",
    responses=DETAIL_ERRORS,
)
async def get_product(product_id: UUID, _: BillingReadDep, services: BillingServicesDep) -> AdminProductDetailResponse:
    return product_detail_response(await services.admin.products.get(product_id))


@products_router.post(
    "/products",
    response_model=AdminProductDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a credit pack or a subscription product",
    responses=WRITE_ERRORS,
)
async def create_product(
    body: CreateProductRequest, principal: BillingProductsManageDep, services: BillingServicesDep
) -> AdminProductDetailResponse:
    detail = await services.admin.products.create(
        actor_of(principal),
        CreateProductCommand(
            code=body.code,
            kind=body.kind,
            name=body.name,
            price_paise=body.price_paise,
            credits_granted=body.credits_granted,
            plan_key=body.plan_key,
            interval=body.interval,
            description=body.description,
            currency=body.currency,
            sort_order=body.sort_order,
            features=tuple(body.features),
            is_active=body.is_active,
        ),
    )
    return product_detail_response(detail)


@products_router.patch(
    "/products/{product_id}",
    response_model=AdminProductDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Edit a product; financial fields only while no order or subscription uses it",
    responses=WRITE_ERRORS,
)
async def update_product(
    product_id: UUID, body: UpdateProductRequest, principal: BillingProductsManageDep, services: BillingServicesDep
) -> AdminProductDetailResponse:
    detail = await services.admin.products.update(
        actor_of(principal), UpdateProductCommand(product_id=product_id, version=body.version, changes=body.changes())
    )
    return product_detail_response(detail)


@products_router.post(
    "/products/{product_id}/duplicate",
    response_model=AdminProductDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Duplicate a product as the next inactive version",
    responses=WRITE_ERRORS,
)
async def duplicate_product(
    product_id: UUID,
    principal: BillingProductsManageDep,
    services: BillingServicesDep,
    body: DuplicateProductRequest | None = None,
) -> AdminProductDetailResponse:
    overrides = body or DuplicateProductRequest()
    detail = await services.admin.products.duplicate(
        actor_of(principal),
        DuplicateProductCommand(
            product_id=product_id,
            name=overrides.name,
            description=overrides.description,
            price_paise=overrides.price_paise,
            credits_granted=overrides.credits_granted,
            interval=overrides.interval,
            features=tuple(overrides.features) if overrides.features is not None else None,
        ),
    )
    return product_detail_response(detail)


@products_router.post(
    "/products/{product_id}/activate",
    response_model=AdminProductDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Activate a product; subscriptions need a synced plan and a free plan slot",
    responses=WRITE_ERRORS,
)
async def activate_product(
    product_id: UUID, principal: BillingProductsManageDep, services: BillingServicesDep
) -> AdminProductDetailResponse:
    return product_detail_response(await services.admin.products.activate(actor_of(principal), product_id))


@products_router.post(
    "/products/{product_id}/deactivate",
    response_model=AdminProductDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Deactivate a product",
    responses=WRITE_ERRORS,
)
async def deactivate_product(
    product_id: UUID, principal: BillingProductsManageDep, services: BillingServicesDep
) -> AdminProductDetailResponse:
    return product_detail_response(await services.admin.products.deactivate(actor_of(principal), product_id))


@products_router.post(
    "/products/{product_id}/sync-plan",
    response_model=AdminProductDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Create and link the Razorpay plan of a subscription product",
    responses=PROVIDER_ERRORS,
)
async def sync_product_plan(
    product_id: UUID, principal: BillingProductsManageDep, services: BillingServicesDep
) -> AdminProductDetailResponse:
    return product_detail_response(await services.admin.products.sync_plan(actor_of(principal), product_id))
