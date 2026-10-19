from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

from sqlalchemy import ColumnElement, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.pagination import Cursor, keyset_page
from motionile.modules.billing.admin_records import (
    NewProduct,
    ProductFilter,
    ProductLink,
    ProductLinks,
    ProductRow,
)
from motionile.modules.billing.exceptions import (
    ActivePlanConflictError,
    ProductCodeExistsError,
    ProductImmutableError,
)
from motionile.modules.billing.models import Order, Product, Subscription
from motionile.modules.billing.repository import FRESH_ROWS, product_record

CODE_CONSTRAINT = "uq_products_code"
ACTIVE_PLAN_INDEX = "ix_products_plan_key_interval_active"
IMMUTABLE_MARKER = "financially immutable"


class ProductAdminStore(Protocol):
    async def list_products(self, query: ProductFilter, cursor: Cursor | None, limit: int) -> list[ProductRow]: ...
    async def product_row(self, product_id: UUID) -> ProductRow | None: ...
    async def lock_product_row(self, product_id: UUID) -> ProductRow | None: ...
    async def product_links(self, product_id: UUID) -> ProductLinks: ...
    async def insert_product(self, product: NewProduct) -> None: ...
    async def update_product(self, product_id: UUID, expected_version: int, values: Mapping[str, object]) -> bool: ...
    async def codes_with_prefix(self, prefix: str) -> set[str]: ...
    async def active_product_code(self, plan_key: str, interval: str, excluding: UUID) -> str | None: ...
    async def set_plan_id(self, product_id: UUID, razorpay_plan_id: str) -> bool: ...
    async def set_active(self, product_id: UUID, *, active: bool) -> None: ...


USED_BY_ORDER = select(Order.id).where(Order.product_id == Product.id).exists()
USED_BY_SUBSCRIPTION = (
    select(Subscription.id)
    .where(or_(Subscription.product_id == Product.id, Subscription.pending_product_id == Product.id))
    .exists()
)
IS_USED = or_(USED_BY_ORDER, USED_BY_SUBSCRIPTION)


def product_row(model: Product, is_used: bool) -> ProductRow:
    return ProductRow(
        record=product_record(model),
        is_used=is_used,
        supersedes_product_id=model.supersedes_product_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def product_link(model: Product) -> ProductLink:
    return ProductLink(id=model.id, code=model.code, name=model.name, version=model.version)


def product_filters(query: ProductFilter) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if query.kind is not None:
        conditions.append(Product.kind == query.kind)
    if query.is_active is not None:
        conditions.append(Product.is_active.is_(query.is_active))
    if query.is_sample is not None:
        conditions.append(Product.is_sample.is_(query.is_sample))
    if query.search is not None:
        conditions.append(
            or_(
                Product.code.icontains(query.search, autoescape=True),
                Product.name.icontains(query.search, autoescape=True),
            )
        )
    return conditions


class SqlProductAdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_products(self, query: ProductFilter, cursor: Cursor | None, limit: int) -> list[ProductRow]:
        statement = keyset_page(
            select(Product, IS_USED.label("is_used")).where(*product_filters(query)),
            created_at=Product.created_at,
            id_=Product.id,
            cursor=cursor,
            limit=limit,
        ).execution_options(**FRESH_ROWS)
        return [product_row(row[0], bool(row[1])) for row in await self.session.execute(statement)]

    async def product_row(self, product_id: UUID) -> ProductRow | None:
        row = (
            await self.session.execute(
                select(Product, IS_USED.label("is_used"))
                .where(Product.id == product_id)
                .execution_options(**FRESH_ROWS)
            )
        ).one_or_none()
        return product_row(row[0], bool(row[1])) if row is not None else None

    async def lock_product_row(self, product_id: UUID) -> ProductRow | None:
        locked = await self.session.scalar(
            select(Product).where(Product.id == product_id).with_for_update().execution_options(**FRESH_ROWS)
        )
        if locked is None:
            return None
        return await self.product_row(product_id)

    async def product_links(self, product_id: UUID) -> ProductLinks:
        predecessor_id = select(Product.supersedes_product_id).where(Product.id == product_id).scalar_subquery()
        predecessor = await self.session.scalar(
            select(Product).where(Product.id == predecessor_id).execution_options(**FRESH_ROWS)
        )
        successors = await self.session.scalars(
            select(Product)
            .where(Product.supersedes_product_id == product_id)
            .order_by(Product.version, Product.code)
            .execution_options(**FRESH_ROWS)
        )
        return ProductLinks(
            supersedes=product_link(predecessor) if predecessor is not None else None,
            superseded_by=tuple(product_link(model) for model in successors),
        )

    async def insert_product(self, product: NewProduct) -> None:
        model = Product(
            id=product.id,
            code=product.code,
            kind=product.kind,
            plan_key=product.plan_key,
            name=product.name,
            description=product.description,
            price_paise=product.price_paise,
            currency=product.currency,
            interval=product.interval,
            credits_granted=product.credits_granted,
            is_active=product.is_active,
            is_sample=product.is_sample,
            supersedes_product_id=product.supersedes_product_id,
            sort_order=product.sort_order,
            features=list(product.features),
            version=product.version,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(model)
                await self.session.flush()
        except IntegrityError as error:
            if CODE_CONSTRAINT in str(error.orig):
                raise ProductCodeExistsError(f"A product with code {product.code} already exists.") from error
            raise

    async def update_product(self, product_id: UUID, expected_version: int, values: Mapping[str, object]) -> bool:
        statement = (
            update(Product)
            .where(Product.id == product_id, Product.version == expected_version)
            .values(**values)
            .returning(Product.id)
        )
        try:
            async with self.session.begin_nested():
                changed = await self.session.scalar(statement)
        except IntegrityError as error:
            reason = str(error.orig)
            if IMMUTABLE_MARKER in reason:
                raise ProductImmutableError(sorted(values)) from error
            if ACTIVE_PLAN_INDEX in reason:
                raise ActivePlanConflictError from error
            raise
        return changed is not None

    async def codes_with_prefix(self, prefix: str) -> set[str]:
        codes = await self.session.scalars(select(Product.code).where(Product.code.startswith(prefix, autoescape=True)))
        return set(codes)

    async def active_product_code(self, plan_key: str, interval: str, excluding: UUID) -> str | None:
        return await self.session.scalar(
            select(Product.code).where(
                Product.kind == "subscription",
                Product.plan_key == plan_key,
                Product.interval == interval,
                Product.is_active.is_(True),
                Product.id != excluding,
            )
        )

    async def set_plan_id(self, product_id: UUID, razorpay_plan_id: str) -> bool:
        changed = await self.session.scalar(
            update(Product)
            .where(Product.id == product_id, Product.razorpay_plan_id.is_(None))
            .values(razorpay_plan_id=razorpay_plan_id)
            .returning(Product.id)
        )
        return changed is not None

    async def set_active(self, product_id: UUID, *, active: bool) -> None:
        try:
            async with self.session.begin_nested():
                await self.session.execute(update(Product).where(Product.id == product_id).values(is_active=active))
        except IntegrityError as error:
            if ACTIVE_PLAN_INDEX in str(error.orig):
                raise ActivePlanConflictError from error
            raise
