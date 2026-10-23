from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from tests.fakes.settings import make_settings

from motionile.core.config import VoicesSettings
from motionile.core.errors import AppError, handle_app_error, handle_request_validation_error
from motionile.modules.media import FORM_OVERHEAD_BYTES, FormLimits
from motionile.modules.media import music_upload as music_module
from motionile.modules.media import render_bed_upload as bed_module
from motionile.modules.media.music_upload import read_music_upload
from motionile.modules.media.render_bed_upload import read_bed_upload
from motionile.modules.voices.router import audio_upload

CHUNK_BYTES = 64 * 1024
VOICES_LIMIT = 1_048_576
BOUNDARY = "motionile-boundary"
PREAMBLE = (
    f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\nContent-Type: audio/wav\r\n\r\n'
).encode()
MULTIPART_TYPE = f"multipart/form-data; boundary={BOUNDARY}"


@dataclass(slots=True)
class Surface:
    path: str
    limit: int
    code: str


@dataclass(slots=True)
class Produced:
    bytes_sent: int = 0


def build_app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_request_validation_error)
    settings = make_settings().model_copy(update={"voices": VoicesSettings(sample_max_bytes=VOICES_LIMIT)})

    @app.post("/voices")
    async def voices(request: Request) -> dict[str, int]:
        return {"size": len(await audio_upload(request, settings))}

    @app.post("/music")
    async def music(request: Request) -> dict[str, int]:
        return {"size": len((await read_music_upload(request)).content)}

    @app.post("/bed")
    async def bed(request: Request) -> dict[str, int]:
        await read_bed_upload(request)
        return {"size": 0}

    return app


SMALL_LIMITS = FormLimits(VOICES_LIMIT, max_files=2, max_fields=16)
SURFACES = [
    Surface("/voices", VOICES_LIMIT + FORM_OVERHEAD_BYTES, "audio_too_large"),
    Surface("/music", SMALL_LIMITS.max_body_bytes, "music_too_large"),
    Surface("/bed", SMALL_LIMITS.max_body_bytes, "render_upload_too_large"),
]


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(music_module, "MUSIC_FORM_LIMITS", SMALL_LIMITS)
    monkeypatch.setattr(bed_module, "FORM_LIMITS", SMALL_LIMITS)
    async with AsyncClient(transport=ASGITransport(app=build_app()), base_url="http://test") as http:
        yield http


def endless_body(produced: Produced, total_bytes: int) -> Callable[[], AsyncIterator[bytes]]:
    async def generate() -> AsyncIterator[bytes]:
        produced.bytes_sent += len(PREAMBLE)
        yield PREAMBLE
        while produced.bytes_sent < total_bytes:
            produced.bytes_sent += CHUNK_BYTES
            yield b"a" * CHUNK_BYTES

    return generate


async def post_streamed(client: AsyncClient, surface: Surface, total_bytes: int) -> tuple[int, str, Produced]:
    produced = Produced()
    response = await client.post(
        surface.path, content=endless_body(produced, total_bytes)(), headers={"content-type": MULTIPART_TYPE}
    )
    return response.status_code, response.json().get("code", ""), produced


@pytest.mark.parametrize("surface", SURFACES, ids=lambda surface: surface.path)
async def test_a_streamed_body_over_the_limit_stops_being_consumed(client: AsyncClient, surface: Surface) -> None:
    total = surface.limit * 3 + CHUNK_BYTES

    status, code, produced = await post_streamed(client, surface, total)

    assert (status, code) == (413, surface.code)
    assert produced.bytes_sent <= surface.limit + 3 * CHUNK_BYTES
    assert produced.bytes_sent < total


@pytest.mark.parametrize("surface", SURFACES, ids=lambda surface: surface.path)
async def test_a_declared_length_over_the_limit_is_refused_before_any_read(
    client: AsyncClient, surface: Surface
) -> None:
    response = await client.post(
        surface.path,
        content=b"x",
        headers={"content-type": MULTIPART_TYPE, "content-length": str(surface.limit * 2 + 1024 * 1024)},
    )

    assert response.status_code == 413
    assert response.json()["code"] == surface.code


async def test_a_body_within_the_limit_is_accepted(client: AsyncClient) -> None:
    response = await client.post("/voices", files={"file": ("a.wav", b"a" * 1000, "audio/wav")})

    assert (response.status_code, response.json()) == (200, {"size": 1000})


async def test_a_file_one_byte_over_the_limit_is_refused_after_the_body_fits(client: AsyncClient) -> None:
    response = await client.post("/voices", files={"file": ("a.wav", b"a" * (VOICES_LIMIT + 1), "audio/wav")})

    assert (response.status_code, response.json()["code"]) == (413, "audio_too_large")


async def test_voice_uploads_reject_unknown_duplicate_and_non_multipart_bodies(client: AsyncClient) -> None:
    unknown = await client.post("/voices", files={"file": ("a.wav", b"a", "audio/wav")}, data={"admin": "true"})
    missing = await client.post("/voices", data={"note": "x"})
    duplicated = await client.post(
        "/voices", files=[("file", ("a.wav", b"a", "audio/wav")), ("file", ("b.wav", b"b", "audio/wav"))]
    )

    assert unknown.status_code == 422
    assert unknown.json()["errors"][0]["field"] == "body.admin"
    assert missing.status_code == 422
    assert duplicated.status_code == 422


async def test_music_uploads_validate_the_metadata(client: AsyncClient) -> None:
    response = await client.post(
        "/music",
        files={"file": ("a.mp3", b"a", "audio/mpeg")},
        data={"title": "Song", "mood": "calm", "licenseName": "CC", "licenseUrl": "http://insecure.example"},
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "body.licenseUrl"


async def test_music_uploads_parse_every_field(client: AsyncClient) -> None:
    response = await client.post(
        "/music",
        files={"file": ("a.mp3", b"abc", "audio/mpeg")},
        data={
            "title": " Song ",
            "mood": "calm",
            "licenseName": "CC",
            "licenseUrl": "https://example.com/license",
            "bpm": "120",
            "activate": "true",
            "attributionText": "",
        },
    )

    assert (response.status_code, response.json()) == (200, {"size": 3})


async def test_music_uploads_reject_unknown_parts(client: AsyncClient) -> None:
    response = await client.post(
        "/music", files={"file": ("a.mp3", b"a", "audio/mpeg"), "extra": ("e", b"e", "text/plain")}
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "body.extra"
