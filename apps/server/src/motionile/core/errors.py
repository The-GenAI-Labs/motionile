from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import ClassVar

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import computed_field
from pydantic.alias_generators import to_camel
from starlette.exceptions import HTTPException as StarletteHTTPException

from motionile.core.schemas import ResponseModel

PROBLEM_MEDIA_TYPE = "application/problem+json"
PROBLEM_TYPE_PREFIX = "urn:motionile:problem:"
REQUEST_LOCATIONS = frozenset({"body", "query", "path", "header", "cookie"})

logger = structlog.get_logger(__name__)


def problem_type(code: str) -> str:
    return f"{PROBLEM_TYPE_PREFIX}{code}"


class FieldError(ResponseModel):
    field: str
    message: str
    type: str


class ProblemDetails(ResponseModel):
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    code: str
    request_id: str | None = None
    errors: list[FieldError] | None = None

    @computed_field
    @property
    def type(self) -> str:
        return problem_type(self.code)


class AppError(Exception):
    status_code: ClassVar[int] = HTTPStatus.INTERNAL_SERVER_ERROR
    default_code: ClassVar[str] = "internal_error"
    title: ClassVar[str] = "Internal server error"

    def __init__(
        self,
        detail: str | None = None,
        *,
        code: str | None = None,
        headers: Mapping[str, str] | None = None,
        errors: Sequence[FieldError] = (),
    ) -> None:
        super().__init__(detail or self.title)
        self.detail = detail
        self.code = code or self.default_code
        self.headers = dict(headers or {})
        self.errors = list(errors)


class BadRequestError(AppError):
    status_code = HTTPStatus.BAD_REQUEST
    default_code = "bad_request"
    title = "Bad request"


class ValidationAppError(AppError):
    status_code = HTTPStatus.UNPROCESSABLE_CONTENT
    default_code = "validation_failed"
    title = "Validation failed"


class UnauthorizedError(AppError):
    status_code = HTTPStatus.UNAUTHORIZED
    default_code = "unauthorized"
    title = "Authentication required"


class ForbiddenError(AppError):
    status_code = HTTPStatus.FORBIDDEN
    default_code = "forbidden"
    title = "Forbidden"


class NotFoundError(AppError):
    status_code = HTTPStatus.NOT_FOUND
    default_code = "not_found"
    title = "Not found"


class ConflictError(AppError):
    status_code = HTTPStatus.CONFLICT
    default_code = "conflict"
    title = "Conflict"


class PreconditionFailedError(AppError):
    status_code = HTTPStatus.PRECONDITION_FAILED
    default_code = "precondition_failed"
    title = "Precondition failed"


class PayloadTooLargeError(AppError):
    status_code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    default_code = "payload_too_large"
    title = "Payload too large"


class RateLimitedError(AppError):
    status_code = HTTPStatus.TOO_MANY_REQUESTS
    default_code = "rate_limited"
    title = "Too many requests"


class ServiceUnavailableError(AppError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    default_code = "service_unavailable"
    title = "Service unavailable"


def request_id_of(request: Request) -> str | None:
    value: object = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else None


def problem_response(problem: ProblemDetails, *, headers: Mapping[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        problem.model_dump(mode="json", exclude_none=True),
        status_code=problem.status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=dict(headers or {}),
    )


def camelize_location(location: Sequence[str | int]) -> str:
    parts: list[str] = []
    for index, part in enumerate(location):
        if isinstance(part, int):
            parts.append(str(part))
        elif index == 0 and part in REQUEST_LOCATIONS:
            parts.append(part)
        else:
            parts.append(to_camel(part))
    return ".".join(parts)


def app_error_response(request: Request, error: AppError) -> JSONResponse:
    problem = ProblemDetails(
        status=error.status_code,
        code=error.code,
        title=error.title,
        detail=error.detail,
        instance=request.url.path,
        request_id=request_id_of(request),
        errors=error.errors or None,
    )
    return problem_response(problem, headers=error.headers)


def internal_error_response(request: Request) -> JSONResponse:
    problem = ProblemDetails(
        status=HTTPStatus.INTERNAL_SERVER_ERROR,
        code=AppError.default_code,
        title=AppError.title,
        detail="An unexpected error occurred. Quote the request ID when contacting support.",
        instance=request.url.path,
        request_id=request_id_of(request),
    )
    return problem_response(problem)


async def handle_app_error(request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, AppError):
        return internal_error_response(request)
    return app_error_response(request, error)


async def handle_request_validation_error(request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, RequestValidationError):
        return internal_error_response(request)
    field_errors = [
        FieldError(field=camelize_location(item["loc"]), message=str(item["msg"]), type=str(item["type"]))
        for item in error.errors()
    ]
    problem = ProblemDetails(
        status=HTTPStatus.UNPROCESSABLE_CONTENT,
        code=ValidationAppError.default_code,
        title=ValidationAppError.title,
        detail="The request is invalid. See errors for details.",
        instance=request.url.path,
        request_id=request_id_of(request),
        errors=field_errors,
    )
    return problem_response(problem)


async def handle_http_exception(request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, StarletteHTTPException):
        return internal_error_response(request)
    status = HTTPStatus(error.status_code)
    code = status.phrase.lower().replace(" ", "_").replace("-", "_").replace("'", "")
    detail = error.detail if error.detail != status.phrase else None
    problem = ProblemDetails(
        status=status,
        code=code,
        title=status.phrase,
        detail=detail,
        instance=request.url.path,
        request_id=request_id_of(request),
    )
    return problem_response(problem, headers=error.headers)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_request_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)


def problem_responses(*statuses: int) -> dict[int | str, dict[str, object]]:
    return {status: {"model": ProblemDetails, "description": HTTPStatus(status).phrase} for status in statuses}
