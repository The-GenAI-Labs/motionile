from collections.abc import Callable, Mapping
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.ids import new_id
from motionile.core.pagination import Cursor, CursorCodec, build_page
from motionile.core.redis import RedisStore
from motionile.modules.audit import ActorType, AuditEvent
from motionile.modules.billing.admin_records import (
    NewProduct,
    ProductDetail,
    ProductFilter,
    ProductRow,
    RecordPage,
)
from motionile.modules.billing.admin_repository import ProductAdminStore, SqlProductAdminRepository
from motionile.modules.billing.exceptions import (
    ActivePlanConflictError,
    ActivePlanExistsError,
    PaymentProviderRejectedError,
    PaymentProviderUnavailableError,
    PlanNotSyncedError,
    ProductImmutableError,
    ProductNotFoundError,
    ProductNotSubscriptionError,
    ProductVersionConflictError,
)
from motionile.modules.billing.ports import Alert, AuditRecorder, Revalidation, Transaction
from motionile.modules.billing.razorpay.api import PlanParams, RazorpayApi
from motionile.modules.billing.razorpay.exceptions import RazorpayBadRequestError, RazorpayError
from motionile.modules.billing.records import ProductRecord
from motionile.modules.billing.seeding import PERIOD_BY_INTERVAL
from motionile.modules.billing.services.product_rules import (
    CREDIT_PACK,
    SUBSCRIPTION,
    apply_changes,
    changed_protected_fields,
    code_prefix,
    column_values,
    effective_changes,
    next_versioned_code,
    reconcile_plan,
    validate_shape,
)
from motionile.modules.billing.services.products import invalidate_product_cache_after_commit
from motionile.modules.billing.services.provider import is_ambiguous, provider_error

STALE_PRODUCT = "The product changed since you loaded it. Reload and retry."
PLAN_SYNC_UNCONFIRMED = (
    "The payment provider did not confirm the plan. If it was created it is not linked to this product and stays "
    "unused at the provider; retry to create and link a new plan."
)

type StoreOf = Callable[[AsyncSession], ProductAdminStore]


@dataclass(frozen=True)
class CreateProductCommand:
    code: str
    kind: str
    name: str
    price_paise: int
    credits_granted: int
    plan_key: str | None = None
    interval: str | None = None
    description: str | None = None
    currency: str = "INR"
    sort_order: int = 0
    features: tuple[str, ...] = ()
    is_active: bool = False


@dataclass(frozen=True)
class UpdateProductCommand:
    product_id: UUID
    version: int
    changes: Mapping[str, object]


@dataclass(frozen=True)
class DuplicateProductCommand:
    product_id: UUID
    name: str | None = None
    description: str | None = None
    price_paise: int | None = None
    credits_granted: int | None = None
    interval: str | None = None
    features: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ProductAdminDependencies:
    transaction: Transaction
    razorpay: RazorpayApi
    redis: RedisStore
    codec: CursorCodec
    audit: AuditRecorder
    alert: Alert
    revalidate: Revalidation
    store_factory: StoreOf = SqlProductAdminRepository


def plan_params(record: ProductRecord) -> PlanParams:
    if record.interval is None:
        raise ProductNotSubscriptionError
    return PlanParams(
        period=PERIOD_BY_INTERVAL[record.interval],
        interval=1,
        name=record.name,
        amount=record.price_paise,
        currency=record.currency,
        description=record.description,
        notes={"productCode": record.code},
    )


class ProductAdminService:
    def __init__(self, deps: ProductAdminDependencies) -> None:
        self._transaction = deps.transaction
        self._razorpay = deps.razorpay
        self._redis = deps.redis
        self._codec = deps.codec
        self._audit = deps.audit
        self._alert = deps.alert
        self._revalidate = deps.revalidate
        self._store_factory = deps.store_factory

    async def list(self, query: ProductFilter, cursor_token: str | None, limit: int) -> RecordPage[ProductRow]:
        cursor = self._codec.decode(cursor_token) if cursor_token else None
        async with self._transaction() as session:
            rows = await self._store_factory(session).list_products(query, cursor, limit)
        items, next_cursor = build_page(
            rows, limit=limit, codec=self._codec, key=lambda row: Cursor(row.created_at, row.record.id)
        )
        return RecordPage(items, next_cursor)

    async def get(self, product_id: UUID) -> ProductDetail:
        async with self._transaction() as session:
            return await self._detail(self._store_factory(session), product_id)

    async def create(self, admin_id: UUID | None, command: CreateProductCommand) -> ProductDetail:
        validate_shape(command.kind, command.plan_key, command.interval)
        product = NewProduct(
            id=new_id(),
            code=command.code,
            kind=command.kind,
            name=command.name,
            price_paise=command.price_paise,
            credits_granted=command.credits_granted,
            plan_key=command.plan_key,
            description=command.description,
            currency=command.currency,
            interval=command.interval,
            is_active=command.is_active and command.kind == CREDIT_PACK,
            sort_order=command.sort_order,
            features=command.features,
        )
        async with self._transaction() as session:
            store = self._store_factory(session)
            await store.insert_product(product)
            await self._record(session, admin_id, "billing.product.created", product.id, {"code": product.code})
            self._publish(session)
            return await self._detail(store, product.id)

    async def update(self, admin_id: UUID | None, command: UpdateProductCommand) -> ProductDetail:
        async with self._transaction() as session:
            store = self._store_factory(session)
            row = await self._locked(store, command.product_id)
            current = row.record
            if current.version != command.version:
                raise ProductVersionConflictError(STALE_PRODUCT)
            effective = effective_changes(current, command.changes)
            if not effective:
                return await self._detail(store, current.id)
            protected = changed_protected_fields(effective)
            if protected and row.is_used:
                raise ProductImmutableError(protected)
            merged = apply_changes(current, effective)
            validate_shape(merged.kind, merged.plan_key, merged.interval)
            merged, forced = reconcile_plan(current, merged, effective)
            values = {**column_values(effective), **forced, "version": current.version + 1}
            if merged.is_active and merged.plan_key is not None and merged.interval is not None:
                await self._require_free_plan(store, merged)
            try:
                updated = await store.update_product(current.id, current.version, values)
            except ActivePlanConflictError:
                await self._require_free_plan(store, merged)
                raise
            if not updated:
                raise ProductVersionConflictError(STALE_PRODUCT)
            await self._record(session, admin_id, "billing.product.updated", current.id, {"fields": sorted(effective)})
            self._publish(session)
            return await self._detail(store, current.id)

    async def duplicate(self, admin_id: UUID | None, command: DuplicateProductCommand) -> ProductDetail:
        async with self._transaction() as session:
            store = self._store_factory(session)
            source = (await self._locked(store, command.product_id)).record
            interval = command.interval or source.interval
            validate_shape(source.kind, source.plan_key, interval)
            taken = await store.codes_with_prefix(code_prefix(source.code))
            created = NewProduct(
                id=new_id(),
                code=next_versioned_code(source.code, source.version + 1, taken),
                kind=source.kind,
                plan_key=source.plan_key,
                name=command.name or source.name,
                description=command.description if command.description is not None else source.description,
                price_paise=command.price_paise or source.price_paise,
                currency=source.currency,
                interval=interval,
                credits_granted=command.credits_granted or source.credits_granted,
                is_active=False,
                is_sample=False,
                sort_order=source.sort_order,
                features=command.features if command.features is not None else source.features,
                version=source.version + 1,
                supersedes_product_id=source.id,
            )
            await store.insert_product(created)
            await self._record(
                session,
                admin_id,
                "billing.product.duplicated",
                created.id,
                {"code": created.code, "sourceId": str(source.id), "sourceCode": source.code},
            )
            self._publish(session)
            return await self._detail(store, created.id)

    async def activate(self, admin_id: UUID | None, product_id: UUID) -> ProductDetail:
        async with self._transaction() as session:
            store = self._store_factory(session)
            record = (await self._locked(store, product_id)).record
            if record.is_active:
                return await self._detail(store, product_id)
            if record.kind == SUBSCRIPTION:
                if record.razorpay_plan_id is None:
                    raise PlanNotSyncedError("Sync the Razorpay plan before activating this subscription product.")
                if record.plan_key is not None and record.interval is not None:
                    await self._require_free_plan(store, record)
            try:
                await store.set_active(product_id, active=True)
            except ActivePlanConflictError:
                await self._require_free_plan(store, record)
                raise
            await self._record(session, admin_id, "billing.product.activated", product_id, {"code": record.code})
            self._publish(session)
            return await self._detail(store, product_id)

    async def deactivate(self, admin_id: UUID | None, product_id: UUID) -> ProductDetail:
        async with self._transaction() as session:
            store = self._store_factory(session)
            record = (await self._locked(store, product_id)).record
            if not record.is_active:
                return await self._detail(store, product_id)
            await store.set_active(product_id, active=False)
            await self._record(session, admin_id, "billing.product.deactivated", product_id, {"code": record.code})
            self._publish(session)
            return await self._detail(store, product_id)

    async def sync_plan(self, admin_id: UUID | None, product_id: UUID) -> ProductDetail:
        async with self._transaction() as session:
            store = self._store_factory(session)
            record = (await self._require(store, product_id)).record
            if record.kind != SUBSCRIPTION:
                raise ProductNotSubscriptionError("Only subscription products have a Razorpay plan.")
            if record.razorpay_plan_id is not None:
                return await self._detail(store, product_id)
        plan_id = await self._create_plan(record)
        async with self._transaction() as session:
            store = self._store_factory(session)
            locked = await self._locked(store, product_id)
            if locked.record.razorpay_plan_id is None and await store.set_plan_id(product_id, plan_id):
                await self._record(
                    session,
                    admin_id,
                    "billing.product.plan_synced",
                    product_id,
                    {"code": record.code, "razorpayPlanId": plan_id},
                )
                self._publish(session)
            return await self._detail(store, product_id)

    async def _create_plan(self, record: ProductRecord) -> str:
        try:
            return (await self._razorpay.create_plan(plan_params(record))).id
        except RazorpayBadRequestError as error:
            raise PaymentProviderRejectedError("The payment provider rejected the plan.") from error
        except RazorpayError as error:
            if not is_ambiguous(error):
                raise provider_error(error) from error
            self._alert("billing.plan_sync_unconfirmed", product_id=str(record.id), error_type=type(error).__name__)
            raise PaymentProviderUnavailableError(PLAN_SYNC_UNCONFIRMED) from error

    async def _require(self, store: ProductAdminStore, product_id: UUID) -> ProductRow:
        row = await store.product_row(product_id)
        if row is None:
            raise ProductNotFoundError
        return row

    async def _locked(self, store: ProductAdminStore, product_id: UUID) -> ProductRow:
        row = await store.lock_product_row(product_id)
        if row is None:
            raise ProductNotFoundError
        return row

    async def _detail(self, store: ProductAdminStore, product_id: UUID) -> ProductDetail:
        row = await self._require(store, product_id)
        return ProductDetail(row, await store.product_links(product_id))

    @staticmethod
    async def _require_free_plan(store: ProductAdminStore, record: ProductRecord) -> None:
        if record.plan_key is None or record.interval is None:
            return
        active_code = await store.active_product_code(record.plan_key, record.interval, record.id)
        if active_code is not None:
            raise ActivePlanExistsError(active_code)

    def _publish(self, session: AsyncSession) -> None:
        invalidate_product_cache_after_commit(session, self._redis)
        self._revalidate(session)

    async def _record(
        self, session: AsyncSession, admin_id: UUID | None, action: str, product_id: UUID, metadata: dict[str, object]
    ) -> None:
        await self._audit(
            session,
            AuditEvent(
                action=action,
                actor_type=ActorType.ADMIN,
                actor_user_id=admin_id,
                target_type="product",
                target_id=str(product_id),
                metadata=metadata,
            ),
        )
