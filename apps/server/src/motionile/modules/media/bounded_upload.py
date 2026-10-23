from collections.abc import AsyncGenerator, Collection
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.datastructures import FormData, UploadFile
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException, MultiPartParser

from motionile.core.errors import BadRequestError, PayloadTooLargeError, ValidationAppError
from motionile.core.openapi import COMPONENT_SCHEMAS_EXTENSION

MULTIPART = "multipart/form-data"
FIELD_BYTES = 256 * 1024
FORM_OVERHEAD_BYTES = 256 * 1024
EXTRA_MESSAGE = "Extra inputs are not permitted"


@dataclass(frozen=True, slots=True)
class FormLimits:
    max_body_bytes: int
    max_files: int
    max_fields: int
    max_field_bytes: int = FIELD_BYTES


def forbidden(names: list[str]) -> RequestValidationError:
    return RequestValidationError(
        [{"type": "extra_forbidden", "loc": ("body", name), "msg": EXTRA_MESSAGE} for name in sorted(names)]
    )


def missing(name: str) -> RequestValidationError:
    return RequestValidationError([{"type": "missing", "loc": ("body", name), "msg": "Field required"}])


def invalid_fields(error: ValidationError, prefix: tuple[str, ...] = ()) -> RequestValidationError:
    return RequestValidationError(
        [{"type": item["type"], "loc": ("body", *prefix, *item["loc"]), "msg": item["msg"]} for item in error.errors()]
    )


async def counted_stream(request: Request, limit: int, too_large: type[PayloadTooLargeError]) -> AsyncGenerator[bytes]:
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise too_large
        yield chunk


async def parse_bounded_form(
    request: Request,
    limits: FormLimits,
    too_large: type[PayloadTooLargeError],
    *,
    required_field: str | None = None,
) -> FormData:
    if not request.headers.get("content-type", "").lower().startswith(MULTIPART):
        if required_field is not None:
            raise missing(required_field)
        raise BadRequestError("The body must be multipart/form-data.", code="multipart_required")
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limits.max_body_bytes:
        raise too_large
    parser = MultiPartParser(
        request.headers,
        counted_stream(request, limits.max_body_bytes, too_large),
        max_files=limits.max_files,
        max_fields=limits.max_fields,
        max_part_size=limits.max_field_bytes,
    )
    try:
        return await parser.parse()
    except MultiPartException:
        raise BadRequestError("The multipart body is malformed.", code="malformed_multipart") from None
    except HTTPException:
        raise BadRequestError("The multipart body has too many parts.", code="malformed_multipart") from None


def unique_parts(form: FormData, allowed: Collection[str]) -> dict[str, str | UploadFile]:
    names = [name for name, _ in form.multi_items()]
    if len(set(names)) != len(names):
        raise ValidationAppError("Every part may appear only once.", code="duplicate_part")
    unknown = [name for name in names if name not in allowed]
    if unknown:
        raise forbidden(unknown)
    return dict(form.multi_items())


async def read_upload_part(part: UploadFile, limit: int, too_large: type[PayloadTooLargeError]) -> bytes:
    data = await part.read(limit + 1)
    if len(data) > limit:
        raise too_large
    return data


def multipart_body(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "requestBody": {
            "required": True,
            "content": {MULTIPART: {"schema": {"$ref": f"#/components/schemas/{name}"}}},
        },
        COMPONENT_SCHEMAS_EXTENSION: {name: schema},
    }


def file_upload_schema(name: str) -> dict[str, Any]:
    return {
        "properties": {"file": {"contentMediaType": "application/octet-stream", "title": "File", "type": "string"}},
        "required": ["file"],
        "title": name,
        "type": "object",
    }
