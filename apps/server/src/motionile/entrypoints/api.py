from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from motionile import __version__
from motionile.core.config import AppEnv, Settings, get_settings
from motionile.core.health import health_router
from motionile.core.logging import configure_logging
from motionile.core.middleware.security_headers import SecurityHeadersMiddleware

API_TITLE = "Motionile API"


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    configure_logging(resolved)
    exposes_docs = resolved.app_env is not AppEnv.PRODUCTION
    app = FastAPI(
        title=API_TITLE,
        version=__version__,
        docs_url="/docs" if exposes_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if exposes_docs else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key"],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(health_router)
    return app


app = create_app()
