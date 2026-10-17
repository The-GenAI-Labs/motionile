import argparse
import asyncio
import sys

from motionile.core.config import AppEnv, get_settings
from motionile.core.resources import build_resources
from motionile.modules.billing import RazorpayError, razorpay_for, seed_products

SEEDABLE_ENVIRONMENTS = (AppEnv.LOCAL, AppEnv.CI, AppEnv.STAGING)
EXIT_REFUSED = 2


def requested_problem(requested: str) -> str | None:
    if requested == AppEnv.PRODUCTION.value:
        return "Sample products are never seeded in production."
    if requested not in {environment.value for environment in SEEDABLE_ENVIRONMENTS}:
        allowed = ", ".join(environment.value for environment in SEEDABLE_ENVIRONMENTS)
        return f"Unknown environment {requested!r}; use one of {allowed}."
    return None


def mismatch_problem(requested: str, actual: AppEnv) -> str | None:
    if actual is AppEnv.PRODUCTION:
        return "Sample products are never seeded in production."
    if requested != actual.value:
        return f"--env {requested} does not match APP_ENV {actual.value}."
    return None


def environment_problem(requested: str, actual: AppEnv) -> str | None:
    return requested_problem(requested) or mismatch_problem(requested, actual)


async def run(environment: str) -> int:
    problem = requested_problem(environment)
    if problem is not None:
        sys.stderr.write(f"{problem}\n")
        return EXIT_REFUSED
    settings = get_settings()
    problem = mismatch_problem(environment, settings.app.env)
    if problem is not None:
        sys.stderr.write(f"{problem}\n")
        return EXIT_REFUSED
    resources = build_resources(settings, application_name="motionile-seed-products")
    try:
        report = await seed_products(resources.database.transaction, razorpay_for(resources))
    except RazorpayError as error:
        sys.stderr.write(f"Razorpay rejected the plan request: {error}\n")
        return 1
    finally:
        await resources.aclose()
    sys.stdout.write(
        f"Saved {report.saved} products, created {report.plans_created} plans, "
        f"activated {report.activated}, skipped {report.skipped}.\n"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create or refresh the sample credit packs and subscription plans.")
    parser.add_argument("--env", required=True, help="local, ci or staging; must match APP_ENV")
    arguments = parser.parse_args(argv)
    return asyncio.run(run(arguments.env))


if __name__ == "__main__":
    sys.exit(main())
