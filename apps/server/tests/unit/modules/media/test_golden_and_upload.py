import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from tests.fakes.settings import make_settings

from motionile.core.config import RenderSettings
from motionile.core.errors import AppError, handle_app_error, handle_request_validation_error
from motionile.modules.media import GoldenNotFoundError
from motionile.modules.media.golden import GoldenCatalog, golden_directory, list_names
from motionile.modules.media.render_bed_upload import MAX_BODY_BYTES, read_bed_upload
from motionile.modules.media.render_commands import COMPOSITION_MAX_BYTES

OPTIONS = json.dumps(
    {
        "aspects": ["16:9"],
        "narration": {
            "mode": "upload",
            "scenes": [{"sceneId": "intro", "audioPart": "audio-intro"}],
        },
    }
)


def make_golden(root: Path, name: str, *, title: str = "Title") -> None:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "composition.html").write_text(f"<html><head><title>{title}</title></head></html>", "utf-8")
    narration = {"language": "en", "scenes": [{"sceneId": "one", "text": "Hello"}]}
    (directory / "narration.json").write_text(json.dumps(narration), "utf-8")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    base = tmp_path / "golden"
    make_golden(base, "kinetic-typography", title="Kinetic &amp; typography")
    make_golden(base, "plain")
    (base / "incomplete").mkdir()
    (base / "incomplete" / "composition.html").write_text("<html></html>", "utf-8")
    (base / "stray.txt").write_text("x", "utf-8")
    return base


async def test_the_catalog_lists_complete_directories_only(root: Path) -> None:
    catalog = GoldenCatalog(root)

    names = await catalog.names()
    items = {item.name: item for item in await catalog.compositions()}

    assert names == ["kinetic-typography", "plain"]
    assert items["kinetic-typography"].title == "Kinetic & typography"
    assert items["kinetic-typography"].description.startswith("Words appearing")
    assert items["plain"].description == "Title"
    assert [scene.scene_id for scene in items["plain"].scenes] == ["one"]
    assert items["plain"].language == "en"


@pytest.mark.parametrize(
    "name",
    [
        "../golden",
        "..",
        ".",
        "/etc/passwd",
        "kinetic-typography/../plain",
        "incomplete",
        "missing",
        "",
        "C:\\x",
        "a\x00b",
    ],
)
async def test_names_are_validated_against_the_listing(root: Path, name: str) -> None:
    with pytest.raises(GoldenNotFoundError):
        await GoldenCatalog(root).load(name)


async def test_a_listed_name_loads_its_composition(root: Path) -> None:
    golden = await GoldenCatalog(root).load("plain")

    assert "<title>Title</title>" in golden.html


async def test_a_missing_directory_gives_an_empty_catalog(tmp_path: Path) -> None:
    catalog = GoldenCatalog(tmp_path / "nowhere")

    assert await catalog.names() == []
    with pytest.raises(GoldenNotFoundError):
        await catalog.load("plain")


def test_a_symlink_that_leaves_the_catalog_is_not_listed(root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    make_golden(outside, "escape")
    try:
        (root / "escape").symlink_to(outside / "escape", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not available")

    assert "escape" not in list_names(root)


def test_the_default_directory_points_at_the_repository_fixtures() -> None:
    directory = golden_directory(make_settings())

    assert directory.parts[-3:] == ("tests", "fixtures", "compositions")
    assert (directory / "kinetic-typography" / "composition.html").is_file()


def test_the_configured_directory_wins(tmp_path: Path) -> None:
    settings = make_settings().model_copy(update={"render": RenderSettings(golden_directory=tmp_path)})

    assert golden_directory(settings) == tmp_path


class Echo(BaseModel):
    composition: str
    options: dict[str, Any]
    audio: dict[str, int]


def build_app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_request_validation_error)

    @app.post("/bed", response_model=Echo)
    async def receive(request: Request) -> Echo:
        upload = await read_bed_upload(request)
        return Echo(
            composition=upload.composition,
            options=upload.options.model_dump(mode="json", by_alias=True),
            audio={name: len(data) for name, data in upload.audio.items()},
        )

    return app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=build_app()), base_url="http://test") as http:
        yield http


async def test_a_valid_multipart_body_is_parsed(client: AsyncClient) -> None:
    response = await client.post(
        "/bed",
        data={"options": OPTIONS},
        files={
            "composition": ("c.html", b"<html></html>", "text/html"),
            "audio-intro": ("a.wav", b"RIFFxxxx", "audio/wav"),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["composition"] == "<html></html>"
    assert body["audio"] == {"audio-intro": 8}
    assert body["options"]["narration"]["scenes"][0]["audioPart"] == "audio-intro"


async def test_unknown_parts_are_rejected_like_extra_fields(client: AsyncClient) -> None:
    response = await client.post(
        "/bed",
        data={"options": OPTIONS, "surprise": "1"},
        files={"composition": ("c.html", b"<html></html>", "text/html")},
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["type"] == "extra_forbidden"
    assert response.json()["errors"][0]["field"] == "body.surprise"


async def test_a_file_part_that_no_scene_names_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/bed",
        data={"options": OPTIONS},
        files={"composition": ("c.html", b"<html></html>", "text/html"), "stray": ("a.wav", b"x", "audio/wav")},
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "body.stray"


async def test_missing_parts_are_reported(client: AsyncClient) -> None:
    no_composition = await client.post("/bed", data={"options": OPTIONS}, files={"x": ("x", b"x", "text/plain")})
    no_options = await client.post("/bed", files={"composition": ("c.html", b"<html></html>", "text/html")})

    assert no_composition.status_code == 422
    assert no_options.status_code == 422
    assert no_options.json()["errors"][0]["field"] == "body.options"


async def test_invalid_options_are_reported_under_the_options_field(client: AsyncClient) -> None:
    response = await client.post(
        "/bed",
        data={"options": json.dumps({"aspects": [], "narration": {"mode": "upload", "scenes": []}})},
        files={"composition": ("c.html", b"<html></html>", "text/html")},
    )

    assert response.status_code == 422
    assert all(error["field"].startswith("body.options") for error in response.json()["errors"])


async def test_options_that_are_not_json_are_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/bed", data={"options": "{nope"}, files={"composition": ("c.html", b"<html></html>", "text/html")}
    )

    assert response.status_code == 422


async def test_a_non_multipart_body_is_a_bad_request(client: AsyncClient) -> None:
    response = await client.post("/bed", json={"options": {}})

    assert response.status_code == 400
    assert response.json()["code"] == "multipart_required"


async def test_a_declared_body_over_the_limit_is_refused_before_reading(client: AsyncClient) -> None:
    response = await client.post(
        "/bed",
        content=b"x",
        headers={"content-type": "multipart/form-data; boundary=x", "content-length": str(MAX_BODY_BYTES + 1)},
    )

    assert response.status_code == 413
    assert response.json()["code"] == "render_upload_too_large"


async def test_an_oversized_composition_is_a_413(client: AsyncClient) -> None:
    response = await client.post(
        "/bed",
        data={"options": OPTIONS},
        files={"composition": ("c.html", b"a" * (COMPOSITION_MAX_BYTES + 1), "text/html")},
    )

    assert response.status_code == 413
    assert response.json()["code"] == "composition_too_large"


async def test_a_composition_that_is_not_utf8_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/bed", data={"options": OPTIONS}, files={"composition": ("c.html", b"\xff\xfe\x00", "text/html")}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "composition_not_utf8"


async def test_a_malformed_multipart_body_is_a_bad_request(client: AsyncClient) -> None:
    response = await client.post(
        "/bed", content=b"garbage", headers={"content-type": "multipart/form-data; boundary=zzz"}
    )

    assert response.status_code in {400, 422}
