from fastapi import FastAPI

from motionile.core.config import Settings, get_settings
from motionile.core.logging import configure_logging
from motionile.core.resources import Resources, build_resources
from motionile.entrypoints.http_app import HttpAppSpec, build_http_app

MCP_TITLE = "Motionile MCP"
APPLICATION_NAME = "motionile-mcp"


def create_app(settings: Settings | None = None, *, resources: Resources | None = None) -> FastAPI:
    resolved = settings or get_settings()
    configure_logging(resolved)
    return build_http_app(
        HttpAppSpec(title=MCP_TITLE, expose_docs=False),
        settings=resolved,
        resources=resources or build_resources(resolved, application_name=APPLICATION_NAME),
    )


app = create_app()
