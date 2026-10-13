from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from motionile import __version__
from motionile.core.config import AppEnv, Settings
from motionile.core.errors import register_exception_handlers
from motionile.core.health import health_router
from motionile.core.idempotency import IdempotentReplay, handle_idempotent_replay
from motionile.core.middleware.access_log import AccessLogMiddleware
from motionile.core.middleware.origin_guard import OriginGuardMiddleware
from motionile.core.middleware.request_id import REQUEST_ID_HEADER, RequestIdMiddleware
from motionile.core.middleware.security_headers import SecurityHeadersMiddleware
from motionile.core.middleware.unhandled_errors import UnhandledErrorMiddleware
from motionile.core.openapi import install_openapi, operation_id
from motionile.core.resources import Resources

ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
ALLOWED_HEADERS = ["Content-Type", "X-CSRF-Token", "Idempotency-Key", "X-Request-ID", "X-Turnstile-Token"]
EXPOSED_HEADERS = [
    REQUEST_ID_HEADER,
    "RateLimit-Limit",
    "RateLimit-Remaining",
    "RateLimit-Reset",
    "Retry-After",
    "Idempotent-Replayed",
    "Location",
]

type Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def resources_lifespan(extra: Lifespan | None = None) -> Lifespan:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        resources: Resources = app.state.resources
        try:
            if extra is None:
                yield
            else:
                async with extra(app):
                    yield
        finally:
            await resources.aclose()

    return lifespan


def install_middleware(app: FastAPI, settings: Settings) -> None:
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(
        OriginGuardMiddleware,
        allowed_origins=settings.cors.allowed_origins,
        exempt_path_prefixes=settings.cors.origin_guard_exempt_prefixes,
        require_origin=settings.security.require_origin_on_unsafe_methods,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors.allowed_origins),
        allow_credentials=True,
        allow_methods=ALLOWED_METHODS,
        allow_headers=ALLOWED_HEADERS,
        expose_headers=EXPOSED_HEADERS,
        max_age=settings.cors.max_age_seconds,
    )
    app.add_middleware(
        SecurityHeadersMiddleware,
        hsts_max_age_seconds=0 if settings.is_local else settings.security.hsts_max_age_seconds,
    )
    app.add_middleware(AccessLogMiddleware, enabled=settings.logging.access_log)
    app.add_middleware(RequestIdMiddleware)


@dataclass(frozen=True)
class HttpAppSpec:
    title: str
    routers: tuple[APIRouter, ...] = ()
    lifespan_extra: Lifespan | None = None
    expose_docs: bool = True


def build_http_app(spec: HttpAppSpec, *, settings: Settings, resources: Resources) -> FastAPI:
    exposes_docs = spec.expose_docs and settings.app.env is not AppEnv.PRODUCTION
    app = FastAPI(
        title=spec.title,
        version=__version__,
        docs_url="/docs" if exposes_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if exposes_docs else None,
        generate_unique_id_function=operation_id,
        lifespan=resources_lifespan(spec.lifespan_extra),
    )
    app.state.resources = resources
    register_exception_handlers(app)
    app.add_exception_handler(IdempotentReplay, handle_idempotent_replay)
    install_middleware(app, settings)
    app.include_router(health_router)
    for router in spec.routers:
        app.include_router(router)
    install_openapi(app)
    return app
