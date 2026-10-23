from typing import Any

from fastapi import Request
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from motionile.core.schemas import StrictModel
from motionile.modules.media.bounded_upload import (
    FORM_OVERHEAD_BYTES,
    FormLimits,
    file_upload_schema,
    forbidden,
    invalid_fields,
    missing,
    multipart_body,
    parse_bounded_form,
    read_upload_part,
    unique_parts,
)
from motionile.modules.media.exceptions import MusicTooLargeError
from motionile.modules.media.music import MusicUpload
from motionile.modules.media.music_audio import MUSIC_MAX_BYTES
from motionile.modules.media.schemas import AttributionText, Bpm, HttpsUrl, LicenseName, Mood, Title

FILE_FIELD = "file"
UPLOAD_SCHEMA_NAME = "Body_admin_music_upload_music_track"
TEXT_FIELDS = frozenset({"title", "mood", "bpm", "licenseName", "licenseUrl", "attributionText", "activate"})
UPLOAD_FIELDS = TEXT_FIELDS | {FILE_FIELD}
MUSIC_FORM_LIMITS = FormLimits(MUSIC_MAX_BYTES + FORM_OVERHEAD_BYTES, max_files=2, max_fields=len(TEXT_FIELDS) + 2)


class MusicUploadFields(StrictModel):
    title: Title
    mood: Mood
    license_name: LicenseName
    license_url: HttpsUrl
    bpm: Bpm | None = None
    attribution_text: AttributionText | None = None
    activate: bool = False


def music_upload_schema() -> dict[str, Any]:
    schema = file_upload_schema(UPLOAD_SCHEMA_NAME)
    schema["properties"] |= {
        "activate": {"default": False, "title": "Activate", "type": "boolean"},
        "attributionText": {"anyOf": [{"$ref": "#/components/schemas/AttributionText"}, {"type": "null"}]},
        "bpm": {"anyOf": [{"$ref": "#/components/schemas/Bpm"}, {"type": "null"}]},
        "licenseName": {"$ref": "#/components/schemas/LicenseName"},
        "licenseUrl": {"$ref": "#/components/schemas/HttpsUrl"},
        "mood": {"$ref": "#/components/schemas/Mood"},
        "title": {"$ref": "#/components/schemas/Title"},
    }
    schema["required"] = [FILE_FIELD, "title", "mood", "licenseName", "licenseUrl"]
    return schema


MUSIC_UPLOAD_OPENAPI = multipart_body(UPLOAD_SCHEMA_NAME, music_upload_schema())


async def read_music_upload(request: Request) -> MusicUpload:
    form = await parse_bounded_form(request, MUSIC_FORM_LIMITS, MusicTooLargeError, required_field=FILE_FIELD)
    try:
        parts = unique_parts(form, UPLOAD_FIELDS)
        file = parts.pop(FILE_FIELD, None)
        if not isinstance(file, UploadFile):
            raise missing(FILE_FIELD)
        misplaced = [name for name, value in parts.items() if isinstance(value, UploadFile)]
        if misplaced:
            raise forbidden(misplaced)
        text = {name: value for name, value in parts.items() if isinstance(value, str) and value != ""}
        try:
            fields = MusicUploadFields.model_validate(text)
        except ValidationError as error:
            raise invalid_fields(error) from None
        content = await read_upload_part(file, MUSIC_MAX_BYTES, MusicTooLargeError)
    finally:
        await form.close()
    return MusicUpload(
        content=content,
        title=fields.title,
        mood=fields.mood,
        license_name=fields.license_name,
        license_url=fields.license_url,
        bpm=fields.bpm,
        attribution_text=fields.attribution_text,
        activate=fields.activate,
    )
