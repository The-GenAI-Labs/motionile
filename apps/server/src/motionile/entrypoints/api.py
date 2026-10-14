from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, status

from motionile.core.config import Settings, get_settings
from motionile.core.errors import problem_responses
from motionile.core.logging import configure_logging
from motionile.core.ratelimit.limiter import rate_limit
from motionile.core.resources import Resources, build_resources
from motionile.core.tasks.app import create_task_app, open_for_deferring
from motionile.entrypoints.http_app import HttpAppSpec, Lifespan, build_http_app
from motionile.entrypoints.test_support import test_support_router

API_TITLE = "Motionile API"
APPLICATION_NAME = "motionile-api"


def build_v1_router(*, include_test_routes: bool) -> APIRouter:
    router = APIRouter(
        prefix="/v1",
        dependencies=[Depends(rate_limit("api.default"))],
        responses=problem_responses(
            status.HTTP_429_TOO_MANY_REQUESTS,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        ),
    )
    if include_test_routes:
        router.include_router(test_support_router)
    return router


def task_lifespan(settings: Settings) -> Lifespan:
    @asynccontextmanager
    async def open_tasks(_: FastAPI) -> AsyncGenerator[None]:
        async with open_for_deferring(create_task_app(settings), settings):
            yield

    return open_tasks


def create_app(
    settings: Settings | None = None,
    *,
    resources: Resources | None = None,
    include_test_routes: bool | None = None,
) -> FastAPI:
    resolved = settings or get_settings()
    configure_logging(resolved)
    with_test_routes = resolved.test_routes_enabled if include_test_routes is None else include_test_routes
    spec = HttpAppSpec(
        title=API_TITLE,
        routers=(build_v1_router(include_test_routes=with_test_routes and resolved.test_routes_enabled),),
        lifespan_extra=task_lifespan(resolved),
    )
    return build_http_app(
        spec,
        settings=resolved,
        resources=resources or build_resources(resolved, application_name=APPLICATION_NAME),
    )


app = create_app()
