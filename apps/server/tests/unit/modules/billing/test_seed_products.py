from dataclasses import replace

import pytest
from tests.unit.modules.billing.conftest import BillingHarness, pack_product

from motionile.core.config import AppEnv
from motionile.modules.billing import SAMPLE_PRODUCTS, RazorpayServerError, SeedReport, seed_products
from motionile.modules.billing.razorpay.api import PlanPeriod
from motionile.modules.billing.razorpay.fake_store import EntityKind, FaultKind, FaultOperation
from motionile.modules.billing.seeding import plan_params
from motionile.scripts import seed_products as script


def remote_plans(harness: BillingHarness) -> int:
    return sum(1 for kind, _ in harness.razorpay_store.entities if kind is EntityKind.PLAN)


async def run_seed(harness: BillingHarness) -> SeedReport:
    return await seed_products(harness.world.transaction, harness.razorpay, store_factory=harness.billing)


def test_the_sample_catalog_matches_the_agreed_offer() -> None:
    offer = {
        spec.code: (spec.kind, spec.price_paise, spec.credits_granted, spec.interval, spec.plan_key)
        for spec in SAMPLE_PRODUCTS
    }

    assert offer == {
        "pack_starter": ("credit_pack", 19_900, 100, None, None),
        "pack_creator": ("credit_pack", 79_900, 500, None, None),
        "pack_studio": ("credit_pack", 199_900, 1_500, None, None),
        "pro_monthly": ("subscription", 49_900, 300, "month", "pro"),
        "pro_yearly": ("subscription", 499_900, 3_600, "year", "pro"),
        "team_monthly": ("subscription", 149_900, 1_200, "month", "team"),
        "team_yearly": ("subscription", 1_499_900, 14_400, "year", "team"),
    }


def test_plan_parameters_follow_the_product() -> None:
    monthly = next(spec for spec in SAMPLE_PRODUCTS if spec.code == "pro_monthly")
    yearly = next(spec for spec in SAMPLE_PRODUCTS if spec.code == "team_yearly")

    assert (plan_params(monthly).period, plan_params(monthly).amount, plan_params(monthly).interval) == (
        PlanPeriod.MONTHLY,
        49_900,
        1,
    )
    assert (plan_params(yearly).period, plan_params(yearly).amount) == (PlanPeriod.YEARLY, 1_499_900)
    assert plan_params(yearly).notes == {"productCode": "team_yearly"}


def test_a_credit_pack_has_no_plan() -> None:
    with pytest.raises(ValueError, match="not a subscription"):
        plan_params(SAMPLE_PRODUCTS[0])


async def test_seeding_creates_active_sample_products_and_plans(billing_harness: BillingHarness) -> None:
    billing_harness.billing.products.clear()

    report = await run_seed(billing_harness)

    assert (report.saved, report.plans_created, report.activated, report.skipped) == (7, 4, 4, 0)
    products = list(billing_harness.billing.products.values())
    assert len(products) == 7
    assert all(product.is_sample and product.is_active for product in products)
    plans = [product for product in products if product.kind == "subscription"]
    assert all(product.razorpay_plan_id is not None for product in plans)
    assert len({product.razorpay_plan_id for product in plans}) == 4
    assert all(product.razorpay_plan_id is None for product in products if product.kind == "credit_pack")
    assert remote_plans(billing_harness) == 4


async def test_seeding_twice_changes_nothing_the_second_time(billing_harness: BillingHarness) -> None:
    billing_harness.billing.products.clear()
    await run_seed(billing_harness)
    before = {product.code: product for product in billing_harness.billing.products.values()}

    report = await run_seed(billing_harness)

    assert (report.saved, report.plans_created, report.activated) == (7, 0, 0)
    after = {product.code: product for product in billing_harness.billing.products.values()}
    assert after == before
    assert remote_plans(billing_harness) == 4


async def test_a_plan_is_activated_only_after_its_id_is_stored(billing_harness: BillingHarness) -> None:
    billing_harness.billing.products.clear()
    await billing_harness.razorpay_store.add_fault(FaultOperation.CREATE_PLAN, FaultKind.SERVER_ERROR, 1)

    with pytest.raises(RazorpayServerError):
        await run_seed(billing_harness)

    stalled = [product for product in billing_harness.billing.products.values() if product.kind == "subscription"]
    assert stalled
    assert all(not product.is_active and product.razorpay_plan_id is None for product in stalled)

    report = await run_seed(billing_harness)

    assert report.activated == 4
    assert all(product.is_active for product in billing_harness.billing.products.values())


async def test_an_existing_plan_id_is_reused_not_recreated(billing_harness: BillingHarness) -> None:
    billing_harness.billing.products.clear()
    await run_seed(billing_harness)
    product = next(item for item in billing_harness.billing.products.values() if item.code == "pro_monthly")
    billing_harness.billing.products[product.id] = replace(product, is_active=False)

    report = await run_seed(billing_harness)

    assert (report.plans_created, report.activated) == (0, 1)
    assert billing_harness.billing.products[product.id].razorpay_plan_id == product.razorpay_plan_id
    assert remote_plans(billing_harness) == 4


async def test_a_real_product_with_a_sample_code_is_never_overwritten(billing_harness: BillingHarness) -> None:
    billing_harness.billing.products.clear()
    real = billing_harness.billing.add_product(pack_product(code="pack_starter"))

    report = await run_seed(billing_harness)

    assert report.skipped == 1
    assert billing_harness.billing.products[real.id] == real


@pytest.mark.parametrize("environment", ["local", "ci", "staging"])
def test_seedable_environments_must_match_the_running_one(environment: str) -> None:
    assert script.environment_problem(environment, AppEnv(environment)) is None


def test_production_is_always_refused() -> None:
    assert "never seeded in production" in (script.environment_problem("production", AppEnv.PRODUCTION) or "")
    assert "never seeded in production" in (script.environment_problem("production", AppEnv.LOCAL) or "")
    assert "never seeded in production" in (script.environment_problem("staging", AppEnv.PRODUCTION) or "")


def test_a_mismatched_or_unknown_environment_is_refused() -> None:
    assert "does not match" in (script.environment_problem("staging", AppEnv.LOCAL) or "")
    assert "Unknown environment" in (script.environment_problem("prod", AppEnv.LOCAL) or "")


def test_the_command_exits_non_zero_for_production_without_touching_anything(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        message = "resources must not be built when seeding is refused"
        raise AssertionError(message)

    monkeypatch.setattr(script, "build_resources", forbidden)
    monkeypatch.setattr(script, "get_settings", forbidden)

    assert script.main(["--env", "production"]) == script.EXIT_REFUSED != 0
    assert "never seeded in production" in capsys.readouterr().err


def test_the_command_refuses_an_environment_that_differs_from_app_env(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("APP_ENV", "local")

    assert script.main(["--env", "staging"]) == script.EXIT_REFUSED
    assert "does not match APP_ENV local" in capsys.readouterr().err
