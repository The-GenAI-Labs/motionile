from typing import Any, cast

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute

from motionile.core.errors import PROBLEM_MEDIA_TYPE

JSON_MEDIA_TYPE = "application/json"
ERROR_STATUS_PREFIXES = ("4", "5")


def operation_id(route: APIRoute) -> str:
    tag = str(route.tags[0]) if route.tags else "default"
    return f"{tag.replace('-', '_')}_{route.name}"


def problem_media_types(schema: dict[str, Any]) -> dict[str, Any]:
    paths = cast("dict[str, dict[str, dict[str, Any]]]", schema.get("paths", {}))
    for operations in paths.values():
        for operation in operations.values():
            responses = cast("dict[str, dict[str, Any]]", operation.get("responses", {}))
            for status_code, response in responses.items():
                content = cast("dict[str, Any] | None", response.get("content"))
                is_problem = (
                    status_code.startswith(ERROR_STATUS_PREFIXES)
                    and content is not None
                    and "ProblemDetails" in str(content.get(JSON_MEDIA_TYPE, ""))
                )
                if is_problem and content is not None:
                    content[PROBLEM_MEDIA_TYPE] = content.pop(JSON_MEDIA_TYPE)
    return schema


def install_openapi(app: FastAPI) -> None:
    def build() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = get_openapi(
                title=app.title,
                version=app.version,
                routes=app.routes,
                description=app.description,
            )
            app.openapi_schema = problem_media_types(schema)
        return app.openapi_schema

    app.openapi = build
