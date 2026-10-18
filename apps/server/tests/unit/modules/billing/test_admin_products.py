from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from uuid import UUID

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.billing_admin import FakeProductAdminStore
from tests.unit.modules.billing.conftest import BillingHarness, pack_product

from motionile.core.pagination import CursorCodec
from motionile.core.redis import RedisKeyBuilder, RedisStore
from motionile.modules.billing.admin_records import ProductFilter
from motionile.modules.billing.exceptions import (
    ActivePlanExistsError,
    InvalidProductShapeError,
    PaymentProviderRejectedError,
    PaymentProviderUnavailableError,
    PlanNotSyncedError,
    ProductCodeExistsError,
    ProductImmutableError,
    ProductNotFoundError,
    ProductNotSubscriptionError,
    ProductVersionConflictError,
)
from motionile.modules.billing.razorpay.fake_store import FaultKind, FaultOperation
from motionile.modules.billing.records import ProductRecord
from motionile.modules.billing.services.admin_products import (
    CreateProductCommand,
    DuplicateProductCommand,
    ProductAdminDependencies,
    ProductAdminService,
    UpdateProductCommand,
)

ADMIN = UUID(int=7)


@dataclass
class Rig:
    harness: BillingHarness
    store: FakeProductAdminStore
    service: ProductAdminService
    revalidations: list[int] = field(default_factory=list[int])
    alerts: list[str] = field(default_factory=list[str])

    def subscription(self, code: str = "pro_monthly", *, price_paise: int | None = None) -> ProductRecord:
        record = replace(pack_product(code=code, kind="subscription", active=False), razorpay_plan_id=None)
        if price_paise is not None:
            record = replace(record, price_paise=price_paise)
        self.store.add(record)
        return record

    def put(self, record: ProductRecord) -> ProductRecord:
        self.store.add(record)
        return record


@pytest.fixture
async def redis() -> AsyncIterator[RedisStore]:
    client = FakeRedis()
    yield RedisStore(client, RedisKeyBuilder("test"))
    await client.aclose()


@pytest.fixture
def rig(billing_harness: BillingHarness, redis: RedisStore) -> Rig:
    store = FakeProductAdminStore(billing_harness.clock)
    revalidations: list[int] = []
    alerts: list[str] = []

    def revalidate(session: AsyncSession) -> None:
        del session
        revalidations.append(1)

    def alert(code: str, **fields: object) -> None:
        del fields
        alerts.append(code)

    service = ProductAdminService(
        ProductAdminDependencies(
            transaction=billing_harness.world.transaction,
            razorpay=billing_harness.razorpay,
            redis=redis,
            codec=CursorCodec(b"secret"),
            audit=billing_harness.audit,
            alert=alert,
            revalidate=revalidate,
            store_factory=store,
        )
    )
    return Rig(billing_harness, store, service, revalidations, alerts)


def pack_command(**changes: object) -> CreateProductCommand:
    base = CreateProductCommand(code="pack_new", kind="credit_pack", name="New", price_paise=9_900, credits_granted=50)
    return replace(base, **changes)


async def test_creating_a_pack_audits_and_publishes(rig: Rig) -> None:
    detail = await rig.service.create(ADMIN, pack_command(is_active=True, features=("50 credits",)))

    record = detail.row.record
    assert (record.code, record.is_active, record.version, record.features) == ("pack_new", True, 1, ("50 credits",))
    assert rig.harness.audit_actions() == ["billing.product.created"]
    assert rig.harness.audit.events[0].actor_user_id == ADMIN
    assert rig.revalidations == [1]


async def test_a_subscription_is_always_created_inactive(rig: Rig) -> None:
    detail = await rig.service.create(
        ADMIN,
        pack_command(code="pro_month", kind="subscription", plan_key="pro", interval="month", is_active=True),
    )

    assert detail.row.record.is_active is False
    assert detail.row.record.razorpay_plan_id is None


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "subscription"},
        {"kind": "subscription", "plan_key": "pro"},
        {"plan_key": "pro"},
        {"interval": "month"},
    ],
)
async def test_a_product_with_an_inconsistent_shape_is_refused(rig: Rig, changes: dict[str, object]) -> None:
    with pytest.raises(InvalidProductShapeError):
        await rig.service.create(ADMIN, pack_command(**changes))


async def test_a_duplicate_code_is_refused(rig: Rig) -> None:
    await rig.service.create(ADMIN, pack_command())

    with pytest.raises(ProductCodeExistsError):
        await rig.service.create(ADMIN, pack_command())


async def test_a_stale_version_is_a_conflict(rig: Rig) -> None:
    record = rig.store.add(pack_product()).record
    await rig.service.update(ADMIN, UpdateProductCommand(record.id, 1, {"name": "First"}))

    with pytest.raises(ProductVersionConflictError):
        await rig.service.update(ADMIN, UpdateProductCommand(record.id, 1, {"name": "Second"}))

    assert rig.store.rows[record.id].record.name == "First"


async def test_every_effective_edit_bumps_the_version_and_a_no_op_does_not(rig: Rig) -> None:
    record = rig.store.add(pack_product()).record

    unchanged = await rig.service.update(ADMIN, UpdateProductCommand(record.id, 1, {"name": record.name}))
    edited = await rig.service.update(
        ADMIN, UpdateProductCommand(record.id, 1, {"price_paise": 5_000, "features": ("a", "b")})
    )

    assert unchanged.row.record.version == 1
    assert (edited.row.record.version, edited.row.record.price_paise, edited.row.record.features) == (
        2,
        5_000,
        ("a", "b"),
    )
    assert rig.harness.audit_actions() == ["billing.product.updated"]
    assert rig.revalidations == [1]


async def test_a_used_product_keeps_its_money_but_accepts_descriptive_edits(rig: Rig) -> None:
    record = rig.store.add(pack_product(), used=True).record

    with pytest.raises(ProductImmutableError) as refused:
        await rig.service.update(ADMIN, UpdateProductCommand(record.id, 1, {"price_paise": 1, "name": "Changed"}))
    renamed = await rig.service.update(ADMIN, UpdateProductCommand(record.id, 1, {"name": "Changed"}))

    assert refused.value.code == "product_immutable"
    assert "price_paise" in str(refused.value.extensions["fields"])
    assert "Duplicate it as a new version" in str(refused.value.detail)
    assert (renamed.row.record.name, renamed.row.record.price_paise) == ("Changed", record.price_paise)


async def test_changing_the_price_of_a_synced_plan_unlinks_and_deactivates_it(rig: Rig) -> None:
    record = rig.put(replace(pack_product(code="pro_monthly", kind="subscription"), razorpay_plan_id="plan_x"))

    detail = await rig.service.update(ADMIN, UpdateProductCommand(record.id, 1, {"price_paise": 77_700}))

    assert (detail.row.record.razorpay_plan_id, detail.row.record.is_active) == (None, False)


async def test_an_unknown_product_is_not_found(rig: Rig) -> None:
    with pytest.raises(ProductNotFoundError):
        await rig.service.update(ADMIN, UpdateProductCommand(UUID(int=1), 1, {"name": "x"}))
    with pytest.raises(ProductNotFoundError):
        await rig.service.get(UUID(int=1))


async def test_duplicating_creates_the_next_inactive_version(rig: Rig) -> None:
    source = rig.put(
        replace(
            pack_product(code="pro_monthly", kind="subscription"), razorpay_plan_id="plan_1", is_active=True, version=3
        )
    )

    detail = await rig.service.duplicate(
        ADMIN, DuplicateProductCommand(source.id, name="Pro", price_paise=59_900, features=("more",))
    )

    created = detail.row.record
    assert (created.code, created.version, created.is_active, created.is_sample) == ("pro_monthly_v4", 4, False, False)
    assert (created.name, created.price_paise, created.features) == ("Pro", 59_900, ("more",))
    assert (created.razorpay_plan_id, created.plan_key, created.interval) == (None, "pro", "month")
    assert detail.row.supersedes_product_id == source.id
    assert detail.links.supersedes is not None
    assert detail.links.supersedes.code == "pro_monthly"
    assert rig.harness.audit_actions() == ["billing.product.duplicated"]


async def test_duplicating_a_version_continues_from_the_base_and_skips_taken_codes(rig: Rig) -> None:
    source = rig.subscription("pro_monthly_v2")
    rig.store.add(pack_product(code="pro_monthly_v3"))

    detail = await rig.service.duplicate(ADMIN, DuplicateProductCommand(source.id))

    assert detail.row.record.code == "pro_monthly_v4"
    assert detail.row.record.version == 2


async def test_a_pack_cannot_be_duplicated_with_an_interval(rig: Rig) -> None:
    source = rig.store.add(pack_product()).record

    with pytest.raises(InvalidProductShapeError):
        await rig.service.duplicate(ADMIN, DuplicateProductCommand(source.id, interval="year"))


async def test_syncing_a_plan_creates_it_once(rig: Rig) -> None:
    product = rig.subscription()

    first = await rig.service.sync_plan(ADMIN, product.id)
    second = await rig.service.sync_plan(ADMIN, product.id)

    plan_id = first.row.record.razorpay_plan_id
    assert plan_id is not None
    assert second.row.record.razorpay_plan_id == plan_id
    assert rig.harness.audit_actions() == ["billing.product.plan_synced"]
    assert rig.harness.razorpay_store.sequences["plan"] == 1


async def test_a_pack_has_no_plan_to_sync(rig: Rig) -> None:
    pack = rig.store.add(pack_product()).record

    with pytest.raises(ProductNotSubscriptionError):
        await rig.service.sync_plan(ADMIN, pack.id)


async def test_an_ambiguous_provider_failure_is_not_resent_and_alerts(rig: Rig) -> None:
    product = rig.subscription()
    await rig.harness.razorpay_store.add_fault(FaultOperation.CREATE_PLAN, FaultKind.TIMEOUT_AFTER_CREATE, 1)

    with pytest.raises(PaymentProviderUnavailableError) as failed:
        await rig.service.sync_plan(ADMIN, product.id)

    assert "not linked to this product" in str(failed.value.detail)
    assert rig.alerts == ["billing.plan_sync_unconfirmed"]
    assert rig.store.rows[product.id].record.razorpay_plan_id is None
    assert rig.harness.razorpay_store.sequences["plan"] == 1


async def test_a_rejected_plan_is_reported_as_rejected(rig: Rig) -> None:
    product = rig.subscription(price_paise=10)

    with pytest.raises(PaymentProviderRejectedError):
        await rig.service.sync_plan(ADMIN, product.id)


async def test_activation_needs_a_synced_plan(rig: Rig) -> None:
    product = rig.subscription()

    with pytest.raises(PlanNotSyncedError):
        await rig.service.activate(ADMIN, product.id)


async def test_only_one_product_may_be_active_per_plan_and_interval(rig: Rig) -> None:
    old = rig.subscription("pro_monthly")
    new = rig.subscription("pro_monthly_v2")
    await rig.service.sync_plan(ADMIN, old.id)
    await rig.service.sync_plan(ADMIN, new.id)
    await rig.service.activate(ADMIN, old.id)

    with pytest.raises(ActivePlanExistsError) as conflict:
        await rig.service.activate(ADMIN, new.id)
    await rig.service.deactivate(ADMIN, old.id)
    activated = await rig.service.activate(ADMIN, new.id)

    assert conflict.value.extensions == {"activeProductCode": "pro_monthly"}
    assert activated.row.record.is_active


async def test_activating_and_deactivating_are_idempotent(rig: Rig) -> None:
    pack = rig.store.add(pack_product(active=False)).record

    await rig.service.activate(ADMIN, pack.id)
    await rig.service.activate(ADMIN, pack.id)
    await rig.service.deactivate(ADMIN, pack.id)
    await rig.service.deactivate(ADMIN, pack.id)

    assert rig.harness.audit_actions() == ["billing.product.activated", "billing.product.deactivated"]
    assert rig.revalidations == [1, 1]


async def test_listing_filters_and_paginates(rig: Rig) -> None:
    for number in range(3):
        rig.store.add(pack_product(code=f"pack_{number}", active=number != 1))
    rig.subscription("sub_one")

    everything = await rig.service.list(ProductFilter(), None, 2)
    packs = await rig.service.list(ProductFilter(kind="credit_pack", is_active=True, search="PACK_"), None, 10)
    rest = await rig.service.list(ProductFilter(), everything.next_cursor, 2)

    assert len(everything.items) == 2
    assert everything.next_cursor is not None
    assert {row.record.code for row in packs.items} == {"pack_0", "pack_2"}
    assert len(rest.items) == 2
    assert rest.next_cursor is None
