from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.datastructures import FormData, UploadFile
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException, MultiPartParser

from motionile.core.errors import BadRequestError, ValidationAppError
from motionile.modules.media.exceptions import CompositionTooLargeError, RenderUploadTooLargeError
from motionile.modules.media.render_commands import COMPOSITION_MAX_BYTES, UPLOAD_MAX_BYTES
from motionile.modules.media.render_options import MAX_SCENES, RenderOptionsRequest, UploadedScene

MAX_BODY_BYTES = 128 * 1024 * 1024
MAX_FIELD_BYTES = 256 * 1024
MAX_FILE_PARTS = MAX_SCENES + 1
MAX_FIELDS = 4
COMPOSITION_FIELD = "composition"
OPTIONS_FIELD = "options"
MULTIPART = "multipart/form-data"
EXTRA_MESSAGE = "Extra inputs are not permitted"


@dataclass(frozen=True, slots=True)
class BedUpload:
    composition: str
    options: RenderOptionsRequest
    audio: dict[str, bytes]


def forbidden(names: list[str]) -> RequestValidationError:
    return RequestValidationError(
        [{"type": "extra_forbidden", "loc": ("body", name), "msg": EXTRA_MESSAGE} for name in sorted(names)]
    )


def missing(name: str) -> RequestValidationError:
    return RequestValidationError([{"type": "missing", "loc": ("body", name), "msg": "Field required"}])


async def counted(request: Request) -> AsyncGenerator[bytes]:
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_BODY_BYTES:
            raise RenderUploadTooLargeError
        yield chunk


async def parse_form(request: Request) -> FormData:
    if not request.headers.get("content-type", "").lower().startswith(MULTIPART):
        raise BadRequestError("The body must be multipart/form-data.", code="multipart_required")
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise RenderUploadTooLargeError
    parser = MultiPartParser(
        request.headers,
        counted(request),
        max_files=MAX_FILE_PARTS,
        max_fields=MAX_FIELDS,
        max_part_size=MAX_FIELD_BYTES,
    )
    try:
        return await parser.parse()
    except MultiPartException:
        raise BadRequestError("The multipart body is malformed.", code="malformed_multipart") from None
    except HTTPException:
        raise BadRequestError("The multipart body has too many parts.", code="malformed_multipart") from None


def parse_options(raw: str) -> RenderOptionsRequest:
    try:
        return RenderOptionsRequest.model_validate_json(raw)
    except ValidationError as error:
        raise RequestValidationError(
            [
                {"type": item["type"], "loc": ("body", OPTIONS_FIELD, *item["loc"]), "msg": item["msg"]}
                for item in error.errors()
            ]
        ) from None


async def read_part(part: UploadFile, limit: int) -> bytes:
    data = await part.read(limit + 1)
    if len(data) > limit:
        raise RenderUploadTooLargeError
    return data


async def read_bed_upload(request: Request) -> BedUpload:
    form = await parse_form(request)
    try:
        return await extract(form)
    finally:
        await form.close()


async def extract(form: FormData) -> BedUpload:
    names = [name for name, _ in form.multi_items()]
    if len(set(names)) != len(names):
        raise ValidationAppError("Every part may appear only once.", code="duplicate_part")
    fields: dict[str, Any] = dict(form.multi_items())
    composition = fields.pop(COMPOSITION_FIELD, None)
    options_text = fields.pop(OPTIONS_FIELD, None)
    if not isinstance(composition, UploadFile):
        raise missing(COMPOSITION_FIELD)
    if not isinstance(options_text, str):
        raise missing(OPTIONS_FIELD)
    options = parse_options(options_text)
    wanted = {scene.audio_part for scene in options.narration.scenes if isinstance(scene, UploadedScene)}
    unknown = [name for name, value in fields.items() if name not in wanted or not isinstance(value, UploadFile)]
    if unknown:
        raise forbidden(unknown)
    try:
        text = (await read_part(composition, COMPOSITION_MAX_BYTES)).decode("utf-8")
    except RenderUploadTooLargeError:
        raise CompositionTooLargeError from None
    except UnicodeDecodeError:
        raise ValidationAppError("The composition must be UTF-8 text.", code="composition_not_utf8") from None
    audio: dict[str, bytes] = {}
    for name, value in fields.items():
        if isinstance(value, UploadFile):
            audio[name] = await read_part(value, UPLOAD_MAX_BYTES)
    return BedUpload(text, options, audio)
