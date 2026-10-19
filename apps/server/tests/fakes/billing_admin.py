from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import Clock
from motionile.core.pagination import Cursor
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
from motionile.modules.billing.records import ProductRecord

PROTECTED = ("kind", "price_paise", "currency", "interval", "credits_granted")


@dataclass
class FakeProductAdminStore:
    clock: Clock
    rows: dict[UUID, ProductRow] = field(default_factory=dict[UUID, ProductRow])
    used: set[UUID] = field(default_factory=set[UUID])

    def __call__(self, session: AsyncSession) -> "FakeProductAdminStore":
        del session
        return self

    def mark_used(self, product_id: UUID) -> None:
        self.used.add(product_id)
        self.rows[product_id] = replace(self.rows[product_id], is_used=True)

    def add(self, record: ProductRecord, *, used: bool = False, supersedes: UUID | None = None) -> ProductRow:
        now = self.clock.now()
        row = ProductRow(record, used, supersedes, now, now)
        self.rows[record.id] = row
        if used:
            self.used.add(record.id)
        return row

    async def list_products(self, query: ProductFilter, cursor: Cursor | None, limit: int) -> list[ProductRow]:
        rows = [
            row
            for row in self.rows.values()
            if (query.kind is None or row.record.kind == query.kind)
            and (query.is_active is None or row.record.is_active is query.is_active)
            and (query.is_sample is None or row.record.is_sample is query.is_sample)
            and (
                query.search is None
                or query.search.lower() in row.record.code.lower()
                or query.search.lower() in row.record.name.lower()
            )
        ]
        rows.sort(key=lambda row: (row.created_at, row.record.id), reverse=True)
        if cursor is not None:
            rows = [row for row in rows if (row.created_at, row.record.id) < (cursor.created_at, cursor.id)]
        return rows[: limit + 1]

    async def product_row(self, product_id: UUID) -> ProductRow | None:
        return self.rows.get(product_id)

    async def lock_product_row(self, product_id: UUID) -> ProductRow | None:
        return self.rows.get(product_id)

    async def product_links(self, product_id: UUID) -> ProductLinks:
        row = self.rows[product_id]
        predecessor = self.rows.get(row.supersedes_product_id) if row.supersedes_product_id is not None else None
        successors = sorted(
            (item for item in self.rows.values() if item.supersedes_product_id == product_id),
            key=lambda item: (item.record.version, item.record.code),
        )
        return ProductLinks(
            supersedes=link(predecessor) if predecessor is not None else None,
            superseded_by=tuple(link(item) for item in successors),
        )

    async def insert_product(self, product: NewProduct) -> None:
        if any(row.record.code == product.code for row in self.rows.values()):
            raise ProductCodeExistsError
        now = self.clock.now()
        record = ProductRecord(
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
            razorpay_plan_id=None,
            is_active=product.is_active,
            is_sample=product.is_sample,
            sort_order=product.sort_order,
            features=product.features,
            version=product.version,
        )
        self.rows[product.id] = ProductRow(record, False, product.supersedes_product_id, now, now)

    async def update_product(self, product_id: UUID, expected_version: int, values: Mapping[str, object]) -> bool:
        row = self.rows[product_id]
        if row.record.version != expected_version:
            return False
        if row.is_used and any(name in values and getattr(row.record, name) != values[name] for name in PROTECTED):
            raise ProductImmutableError(sorted(values))
        converted = dict(values)
        features = values.get("features")
        if isinstance(features, list):
            converted["features"] = tuple(str(item) for item in cast("list[object]", features))
        self.rows[product_id] = replace(row, record=replace(row.record, **converted), updated_at=self.clock.now())
        return True

    async def codes_with_prefix(self, prefix: str) -> set[str]:
        return {row.record.code for row in self.rows.values() if row.record.code.startswith(prefix)}

    async def active_product_code(self, plan_key: str, interval: str, excluding: UUID) -> str | None:
        return next(
            (
                row.record.code
                for row in self.rows.values()
                if row.record.kind == "subscription"
                and row.record.plan_key == plan_key
                and row.record.interval == interval
                and row.record.is_active
                and row.record.id != excluding
            ),
            None,
        )

    async def set_plan_id(self, product_id: UUID, razorpay_plan_id: str) -> bool:
        row = self.rows[product_id]
        if row.record.razorpay_plan_id is not None:
            return False
        self.rows[product_id] = replace(row, record=replace(row.record, razorpay_plan_id=razorpay_plan_id))
        return True

    async def set_active(self, product_id: UUID, *, active: bool) -> None:
        row = self.rows[product_id]
        if active and row.record.plan_key is not None and row.record.interval is not None:
            conflict = await self.active_product_code(row.record.plan_key, row.record.interval, product_id)
            if conflict is not None:
                raise ActivePlanConflictError
        self.rows[product_id] = replace(row, record=replace(row.record, is_active=active))


def link(row: ProductRow) -> ProductLink:
    return ProductLink(id=row.record.id, code=row.record.code, name=row.record.name, version=row.record.version)
