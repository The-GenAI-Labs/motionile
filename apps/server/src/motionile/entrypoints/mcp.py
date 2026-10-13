from fastapi import FastAPI

from motionile import __version__
from motionile.core.config import Settings, get_settings
from motionile.core.health import health_router
from motionile.core.logging import configure_logging
from motionile.core.middleware.security_headers import SecurityHeadersMiddleware

MCP_TITLE = "Motionile MCP"


def create_app(settings: Settings | None = None) -> FastAPI:
    configure_logging(settings or get_settings())
    app = FastAPI(title=MCP_TITLE, version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(health_router)
    return app


app = create_app()
