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
from motionile.modules.access.router import access_admin_router
from motionile.modules.admin import admin_insights_router
from motionile.modules.auth import (
    AuthRuntime,
    VerificationRequiredError,
    auth_router,
    identify_for_rate_limit,
    verification_required_response,
)
from motionile.modules.catalog.router import catalog_admin_router, catalog_router
from motionile.modules.platform.router import platform_router
from motionile.modules.users.router import users_admin_router, users_router

API_TITLE = "Motionile API"
APPLICATION_NAME = "motionile-api"


def build_v1_router(*, include_test_routes: bool) -> APIRouter:
    router = APIRouter(
        prefix="/v1",
        dependencies=[Depends(identify_for_rate_limit), Depends(rate_limit("api.default"))],
        responses=problem_responses(
            status.HTTP_429_TOO_MANY_REQUESTS,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        ),
    )
    router.include_router(auth_router)
    router.include_router(users_router)
    router.include_router(catalog_router)
    router.include_router(access_admin_router)
    router.include_router(admin_insights_router)
    router.include_router(users_admin_router)
    router.include_router(platform_router)
    router.include_router(catalog_admin_router)
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
    app = build_http_app(
        spec,
        settings=resolved,
        resources=resources or build_resources(resolved, application_name=APPLICATION_NAME),
    )

    app.add_exception_handler(VerificationRequiredError, verification_required_response)
    app.state.auth_runtime = AuthRuntime(app.state.resources)
    return app


app = create_app()
