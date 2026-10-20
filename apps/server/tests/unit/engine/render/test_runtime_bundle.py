import hashlib
import json
from importlib import resources
from pathlib import Path

import pytest

from motionile.engine.render.runtime import (
    COMPOSITION_URL,
    RUNTIME_BASE_URL,
    RUNTIME_ORIGIN,
    RUNTIME_VERSION,
    RuntimeBundle,
    RuntimeBundleError,
    load_assets,
    load_runtime_bundle,
    read_manifest,
)
from motionile.engine.render.runtime.manifest import SERVED_FILES, build_manifest, write_manifest

RUNTIME_PACKAGE = "motionile.engine.render.runtime"
DOCUMENTED_PATHS = {
    "base.css",
    "motionile.js",
    "fonts/fonts.css",
    "gsap/gsap.min.js",
    "gsap/TextPlugin.min.js",
    "gsap/SplitText.min.js",
    "gsap/DrawSVGPlugin.min.js",
    "gsap/MorphSVGPlugin.min.js",
    "gsap/MotionPathPlugin.min.js",
    "gsap/CustomEase.min.js",
    "gsap/LICENSE.md",
}


def test_constants_describe_the_virtual_origin() -> None:
    assert RUNTIME_ORIGIN == "https://runtime.motionile.local"
    assert RUNTIME_VERSION == "v1"
    assert RUNTIME_BASE_URL == "https://runtime.motionile.local/v1/"
    assert COMPOSITION_URL == "https://runtime.motionile.local/composition.html"


def test_every_manifest_hash_matches_the_packaged_file() -> None:
    manifest = read_manifest()
    root = resources.files(RUNTIME_PACKAGE).joinpath(RUNTIME_VERSION)

    assert manifest["files"]
    for entry in manifest["files"]:
        data = root.joinpath(entry["source"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], entry["path"]
        assert len(data) == entry["size"], entry["path"]


def test_the_committed_manifest_equals_a_fresh_build() -> None:
    manifest = json.loads(
        resources.files(RUNTIME_PACKAGE).joinpath(RUNTIME_VERSION, "manifest.json").read_text(encoding="utf-8")
    )

    assert manifest == build_manifest()


def test_bundle_loads_through_importlib_resources_and_serves_the_documented_paths() -> None:
    bundle = load_runtime_bundle()

    assert set(bundle.paths) >= DOCUMENTED_PATHS
    assert {Path(entry.path).name for entry in bundle.font_assets()} >= {
        "geist-latin-wght-normal.woff2",
        "geist-mono-latin-wght-normal.woff2",
        "noto-sans-latin-wght-normal.woff2",
        "noto-sans-devanagari-devanagari-wght-normal.woff2",
    }


def test_manifest_records_versions_and_licenses() -> None:
    manifest = read_manifest()
    components = {component["name"]: component for component in manifest["components"]}

    assert components["gsap"]["version"] == "3.15.0"
    assert "GSAP" in components["gsap"]["license"]
    assert {"Geist", "Geist Mono", "Noto Sans", "Noto Sans Devanagari"} <= set(components)
    assert all(component["version"] for component in components.values())


def test_assets_carry_content_types_and_cache_headers() -> None:
    bundle = load_runtime_bundle()
    script = bundle.asset("gsap/gsap.min.js")
    font = bundle.asset("fonts/geist-latin-wght-normal.woff2")
    stylesheet = bundle.asset("base.css")

    assert script is not None
    assert font is not None
    assert stylesheet is not None
    assert script.content_type.startswith("text/javascript")
    assert font.content_type == "font/woff2"
    assert stylesheet.content_type.startswith("text/css")
    assert script.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    assert script.headers["Access-Control-Allow-Origin"] == "*"
    assert script.headers["X-Content-Type-Options"] == "nosniff"
    assert script.headers["ETag"] == f'"{script.sha256}"'


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://runtime.motionile.local/v1/base.css", True),
        ("https://runtime.motionile.local/v1/base.css?cache=1", True),
        ("https://runtime.motionile.local:443/v1/motionile.js", True),
        ("http://runtime.motionile.local/v1/base.css", False),
        ("https://runtime.motionile.local:8443/v1/base.css", False),
        ("https://runtime.motionile.local/v2/base.css", False),
        ("https://runtime.motionile.local/v1/missing.css", False),
        ("https://evil.test/v1/base.css", False),
        ("https://runtime.motionile.local.evil.test/v1/base.css", False),
    ],
)
def test_asset_for_url_only_matches_the_runtime_origin(url: str, expected: bool) -> None:
    assert (load_runtime_bundle().asset_for_url(url) is not None) is expected


def test_write_fonts_copies_every_font(tmp_path: Path) -> None:
    written = load_runtime_bundle().write_fonts(tmp_path / "fonts")

    assert len(written) == 4
    assert all(path.read_bytes().startswith(b"wOF2") for path in written)


def test_bundle_rejects_a_file_that_does_not_match_its_manifest() -> None:
    manifest = read_manifest()
    tampered = {**manifest, "files": [{**manifest["files"][0], "sha256": "0" * 64}, *manifest["files"][1:]]}

    with pytest.raises(RuntimeBundleError, match="manifest hash"):
        load_assets(tampered)


def test_write_manifest_round_trips(tmp_path: Path) -> None:
    for served in SERVED_FILES:
        target = tmp_path / served.source
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(served.path.encode())

    written = write_manifest(tmp_path)

    assert (
        json.loads(written.read_text(encoding="utf-8"))["files"][0]["sha256"]
        == hashlib.sha256(sorted(SERVED_FILES, key=lambda item: item.path)[0].path.encode()).hexdigest()
    )


def test_bundle_class_is_constructible_from_assets() -> None:
    bundle = RuntimeBundle({}, {"runtime": "v1"})

    assert bundle.paths == ()
    assert bundle.asset("base.css") is None
    assert bundle.version == "v1"


def test_the_authored_runtime_files_have_no_comments_and_no_raw_text_colors() -> None:
    root = resources.files(RUNTIME_PACKAGE).joinpath(RUNTIME_VERSION)
    script = root.joinpath("motionile.js").read_text(encoding="utf-8")
    stylesheet = root.joinpath("base.css").read_text(encoding="utf-8")

    assert "//" not in script.replace("https://", "")
    assert "/*" not in script
    assert "/*" not in stylesheet
    assert "window.__timeline" in script
    assert "window.__composition" in script
    assert "window.__ready" in script
