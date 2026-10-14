from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, Field

from motionile.core.errors import (
    PROBLEM_MEDIA_TYPE,
    AppError,
    BadRequestError,
    ConflictError,
    FieldError,
    ForbiddenError,
    NotFoundError,
    PayloadTooLargeError,
    PreconditionFailedError,
    RateLimitedError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationAppError,
    camelize_location,
    problem_responses,
    problem_type,
    register_exception_handlers,
)
from motionile.core.middleware.request_id import RequestIdMiddleware
from motionile.core.middleware.unhandled_errors import UnhandledErrorMiddleware

ERROR_CASES: list[tuple[type[AppError], int, str]] = [
    (BadRequestError, 400, "bad_request"),
    (UnauthorizedError, 401, "unauthorized"),
    (ForbiddenError, 403, "forbidden"),
    (NotFoundError, 404, "not_found"),
    (ConflictError, 409, "conflict"),
    (PreconditionFailedError, 412, "precondition_failed"),
    (PayloadTooLargeError, 413, "payload_too_large"),
    (ValidationAppError, 422, "validation_failed"),
    (RateLimitedError, 429, "rate_limited"),
    (ServiceUnavailableError, 503, "service_unavailable"),
]


class Payload(BaseModel):
    display_name: str = Field(min_length=3)
    nested_items: list[int]


def build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(RequestIdMiddleware)

    @app.get("/errors/{index}")
    async def raise_error(index: int) -> None:
        error_type = ERROR_CASES[index][0]
        raise error_type("Something specific.", headers={"Retry-After": "7"})

    @app.post("/validate")
    async def validate(payload: Payload) -> Payload:
        return payload

    @app.get("/http")
    async def http_error() -> None:
        raise HTTPException(status_code=418, detail="short and stout")

    @app.get("/boom")
    async def boom() -> None:
        message = "database password=hunter2 leaked"
        raise RuntimeError(message)

    return app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=build_app()), base_url="http://test") as http:
        yield http


@pytest.mark.parametrize(("index", "case"), list(enumerate(ERROR_CASES)))
async def test_app_errors_render_problem_details(
    client: AsyncClient, index: int, case: tuple[type[AppError], int, str]
) -> None:
    _, status, code = case

    response = await client.get(f"/errors/{index}", headers={"X-Request-ID": "req-12345678"})

    assert response.status_code == status
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.headers["retry-after"] == "7"
    body = response.json()
    assert body["type"] == problem_type(code)
    assert body["code"] == code
    assert body["status"] == status
    assert body["detail"] == "Something specific."
    assert body["instance"] == f"/errors/{index}"
    assert body["requestId"] == "req-12345678"


async def test_validation_errors_use_camel_case_paths(client: AsyncClient) -> None:
    response = await client.post("/validate", json={"display_name": "ab", "nested_items": ["x"]})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_failed"
    fields = {error["field"] for error in body["errors"]}
    assert "body.displayName" in fields
    assert "body.nestedItems.0" in fields


async def test_http_exceptions_become_problems(client: AsyncClient) -> None:
    teapot = await client.get("/http")
    missing = await client.get("/missing")
    wrong_method = await client.delete("/http")

    assert teapot.json()["code"] == "im_a_teapot"
    assert teapot.json()["detail"] == "short and stout"
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"
    assert "detail" not in missing.json()
    assert wrong_method.json()["code"] == "method_not_allowed"


async def test_unhandled_errors_never_leak_internals(client: AsyncClient) -> None:
    response = await client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal_error"
    assert "hunter2" not in response.text
    assert body["requestId"] == response.headers["x-request-id"]


def test_camelize_location_keeps_location_prefix() -> None:
    assert camelize_location(("query", "page_size")) == "query.pageSize"
    assert camelize_location(("body", "items", 2, "unit_price")) == "body.items.2.unitPrice"
    assert camelize_location(("some_field",)) == "someField"


def test_problem_responses_reference_problem_details() -> None:
    responses = problem_responses(404, 409)

    assert set(responses) == {404, 409}
    assert responses[404]["description"] == "Not Found"


def test_field_error_serializes() -> None:
    assert FieldError(field="body.x", message="bad", type="value_error").model_dump() == {
        "field": "body.x",
        "message": "bad",
        "type": "value_error",
    }
