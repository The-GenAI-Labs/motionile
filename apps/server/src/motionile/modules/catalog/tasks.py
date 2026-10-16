from typing import cast

import orjson
from procrastinate.types import JSONValue
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.config import get_settings
from motionile.core.resources import build_resources
from motionile.core.tasks.registry import Queue, defer_after_commit, task

SUCCESS_STATUS_MINIMUM = 200
SUCCESS_STATUS_MAXIMUM = 300


@task(name="catalog.revalidate", queue=Queue.DEFAULT)
async def revalidate_catalog(tags: list[str]) -> None:
    settings = get_settings()
    secret = settings.catalog.revalidation_secret
    if secret is None:
        if settings.is_local:
            return
        raise RuntimeError("catalog revalidation secret is missing")
    resources = build_resources(settings, application_name="motionile-catalog-revalidation")
    try:
        response = await resources.provider_clients["catalog_revalidation"].request(
            "POST",
            f"{settings.auth.web_origin.rstrip('/')}/api/revalidate",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {secret.get_secret_value()}"},
            content=orjson.dumps({"tags": tags}),
        )
        if not SUCCESS_STATUS_MINIMUM <= response.status_code < SUCCESS_STATUS_MAXIMUM:
            raise RuntimeError("catalog revalidation failed")
    finally:
        await resources.aclose()


def defer_revalidation(session: AsyncSession, tags: list[str]) -> None:
    defer_after_commit(session, revalidate_catalog, tags=cast("JSONValue", tags))
