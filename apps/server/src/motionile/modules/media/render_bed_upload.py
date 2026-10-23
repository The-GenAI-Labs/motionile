from dataclasses import dataclass
from typing import Any

from fastapi import Request
from pydantic import ValidationError
from starlette.datastructures import FormData, UploadFile

from motionile.core.errors import ValidationAppError
from motionile.modules.media.bounded_upload import (
    FormLimits,
    forbidden,
    invalid_fields,
    missing,
    parse_bounded_form,
    read_upload_part,
)
from motionile.modules.media.exceptions import CompositionTooLargeError, RenderUploadTooLargeError
from motionile.modules.media.render_commands import COMPOSITION_MAX_BYTES, UPLOAD_MAX_BYTES
from motionile.modules.media.render_options import MAX_SCENES, RenderOptionsRequest, UploadedScene

MAX_BODY_BYTES = 128 * 1024 * 1024
MAX_FIELD_BYTES = 256 * 1024
MAX_FILE_PARTS = MAX_SCENES + 1
MAX_FIELDS = 4
FORM_LIMITS = FormLimits(MAX_BODY_BYTES, MAX_FILE_PARTS, MAX_FIELDS, MAX_FIELD_BYTES)
COMPOSITION_FIELD = "composition"
OPTIONS_FIELD = "options"


@dataclass(frozen=True, slots=True)
class BedUpload:
    composition: str
    options: RenderOptionsRequest
    audio: dict[str, bytes]


async def parse_form(request: Request) -> FormData:
    return await parse_bounded_form(request, FORM_LIMITS, RenderUploadTooLargeError)


def parse_options(raw: str) -> RenderOptionsRequest:
    try:
        return RenderOptionsRequest.model_validate_json(raw)
    except ValidationError as error:
        raise invalid_fields(error, (OPTIONS_FIELD,)) from None


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
        text = (await read_upload_part(composition, COMPOSITION_MAX_BYTES, RenderUploadTooLargeError)).decode("utf-8")
    except RenderUploadTooLargeError:
        raise CompositionTooLargeError from None
    except UnicodeDecodeError:
        raise ValidationAppError("The composition must be UTF-8 text.", code="composition_not_utf8") from None
    audio: dict[str, bytes] = {}
    for name, value in fields.items():
        if isinstance(value, UploadFile):
            audio[name] = await read_upload_part(value, UPLOAD_MAX_BYTES, RenderUploadTooLargeError)
    return BedUpload(text, options, audio)
