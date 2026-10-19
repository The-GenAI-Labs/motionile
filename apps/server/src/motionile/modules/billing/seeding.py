from dataclasses import dataclass

from motionile.modules.billing.ports import StoreFactory, Transaction
from motionile.modules.billing.razorpay.api import PlanParams, PlanPeriod, RazorpayApi
from motionile.modules.billing.records import SampleProductSpec
from motionile.modules.billing.repository import SqlBillingRepository

CREDIT_PACK = "credit_pack"
SUBSCRIPTION = "subscription"
PERIOD_BY_INTERVAL = {"month": PlanPeriod.MONTHLY, "year": PlanPeriod.YEARLY}

SAMPLE_PRODUCTS: tuple[SampleProductSpec, ...] = (
    SampleProductSpec(
        code="pack_starter",
        kind=CREDIT_PACK,
        name="Starter",
        description="100 credits for a handful of explainers.",
        price_paise=19_900,
        credits_granted=100,
        sort_order=10,
        features=("100 credits", "Credits never expire", "All video formats"),
    ),
    SampleProductSpec(
        code="pack_creator",
        kind=CREDIT_PACK,
        name="Creator",
        description="500 credits for a steady publishing rhythm.",
        price_paise=79_900,
        credits_granted=500,
        sort_order=20,
        features=("500 credits", "Credits never expire", "All video formats"),
    ),
    SampleProductSpec(
        code="pack_studio",
        kind=CREDIT_PACK,
        name="Studio",
        description="1,500 credits for teams that publish every week.",
        price_paise=199_900,
        credits_granted=1_500,
        sort_order=30,
        features=("1,500 credits", "Credits never expire", "All video formats"),
    ),
    SampleProductSpec(
        code="pro_monthly",
        kind=SUBSCRIPTION,
        name="Pro monthly",
        description="300 credits every month for solo creators.",
        price_paise=49_900,
        credits_granted=300,
        sort_order=10,
        features=("300 credits every month", "Priority rendering"),
        interval="month",
        plan_key="pro",
    ),
    SampleProductSpec(
        code="pro_yearly",
        kind=SUBSCRIPTION,
        name="Pro yearly",
        description="3,600 credits a year for solo creators, billed yearly.",
        price_paise=499_900,
        credits_granted=3_600,
        sort_order=20,
        features=("3,600 credits every year", "Priority rendering"),
        interval="year",
        plan_key="pro",
    ),
    SampleProductSpec(
        code="team_monthly",
        kind=SUBSCRIPTION,
        name="Team monthly",
        description="1,200 credits every month for small teams.",
        price_paise=149_900,
        credits_granted=1_200,
        sort_order=30,
        features=("1,200 credits every month", "Priority rendering", "Shared billing"),
        interval="month",
        plan_key="team",
    ),
    SampleProductSpec(
        code="team_yearly",
        kind=SUBSCRIPTION,
        name="Team yearly",
        description="14,400 credits a year for small teams, billed yearly.",
        price_paise=1_499_900,
        credits_granted=14_400,
        sort_order=40,
        features=("14,400 credits every year", "Priority rendering", "Shared billing"),
        interval="year",
        plan_key="team",
    ),
)


@dataclass
class SeedReport:
    saved: int = 0
    plans_created: int = 0
    activated: int = 0
    skipped: int = 0


def plan_params(spec: SampleProductSpec) -> PlanParams:
    if spec.interval is None:
        message = f"{spec.code} is not a subscription"
        raise ValueError(message)
    return PlanParams(
        period=PERIOD_BY_INTERVAL[spec.interval],
        interval=1,
        name=spec.name,
        amount=spec.price_paise,
        currency="INR",
        description=spec.description,
        notes={"productCode": spec.code},
    )


async def seed_products(
    transaction: Transaction,
    razorpay: RazorpayApi,
    specs: tuple[SampleProductSpec, ...] = SAMPLE_PRODUCTS,
    *,
    store_factory: StoreFactory = SqlBillingRepository,
) -> SeedReport:
    report = SeedReport()
    for spec in specs:
        async with transaction() as session:
            product = await store_factory(session).save_sample_product(spec)
        if product is None:
            report.skipped += 1
            continue
        report.saved += 1
        if spec.kind != SUBSCRIPTION or product.is_active:
            continue
        plan_id = product.razorpay_plan_id
        if plan_id is None:
            plan_id = (await razorpay.create_plan(plan_params(spec))).id
            report.plans_created += 1
        async with transaction() as session:
            if await store_factory(session).activate_product_with_plan(product.id, plan_id):
                report.activated += 1
    return report
