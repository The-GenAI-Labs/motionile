import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RUNTIME_VERSION = "v1"
MANIFEST_NAME = "manifest.json"
SOURCE_DIRECTORY = Path(__file__).resolve().parent / RUNTIME_VERSION

CSS = "text/css; charset=utf-8"
JAVASCRIPT = "text/javascript; charset=utf-8"
WOFF2 = "font/woff2"
PLAIN_TEXT = "text/plain; charset=utf-8"
MARKDOWN = "text/markdown; charset=utf-8"
GSAP_BANNER_LICENSE = "GSAP Standard No Charge License"
GSAP_LICENSE_URL = "https://gsap.com/standard-license"
OFL = "SIL Open Font License 1.1"


@dataclass(frozen=True)
class ServedFile:
    path: str
    source: str
    content_type: str


def gsap_file(name: str) -> ServedFile:
    return ServedFile(f"gsap/{name}", f"vendor/gsap/{name}", JAVASCRIPT)


def font_file(name: str) -> ServedFile:
    return ServedFile(f"fonts/{name}", f"vendor/fonts/{name}", WOFF2)


def font_license(name: str) -> ServedFile:
    return ServedFile(f"fonts/{name}", f"vendor/fonts/{name}", PLAIN_TEXT)


SERVED_FILES: tuple[ServedFile, ...] = (
    ServedFile("base.css", "base.css", CSS),
    ServedFile("motionile.js", "motionile.js", JAVASCRIPT),
    ServedFile("fonts/fonts.css", "fonts/fonts.css", CSS),
    font_file("geist-latin-wght-normal.woff2"),
    font_file("geist-mono-latin-wght-normal.woff2"),
    font_file("noto-sans-latin-wght-normal.woff2"),
    font_file("noto-sans-devanagari-devanagari-wght-normal.woff2"),
    font_license("LICENSE-geist.txt"),
    font_license("LICENSE-geist-mono.txt"),
    font_license("LICENSE-noto-sans.txt"),
    font_license("LICENSE-noto-sans-devanagari.txt"),
    gsap_file("gsap.min.js"),
    gsap_file("TextPlugin.min.js"),
    gsap_file("SplitText.min.js"),
    gsap_file("DrawSVGPlugin.min.js"),
    gsap_file("MorphSVGPlugin.min.js"),
    gsap_file("MotionPathPlugin.min.js"),
    gsap_file("CustomEase.min.js"),
    ServedFile("gsap/LICENSE.md", "vendor/gsap/LICENSE.md", MARKDOWN),
)

COMPONENTS: tuple[dict[str, str], ...] = (
    {
        "name": "gsap",
        "package": "gsap",
        "version": "3.15.0",
        "license": GSAP_BANNER_LICENSE,
        "licenseUrl": GSAP_LICENSE_URL,
    },
    {
        "name": "Geist",
        "package": "@fontsource-variable/geist",
        "version": "5.3.0",
        "license": OFL,
        "licenseUrl": "https://openfontlicense.org",
    },
    {
        "name": "Geist Mono",
        "package": "@fontsource-variable/geist-mono",
        "version": "5.3.0",
        "license": OFL,
        "licenseUrl": "https://openfontlicense.org",
    },
    {
        "name": "Noto Sans",
        "package": "@fontsource-variable/noto-sans",
        "version": "5.3.0",
        "license": OFL,
        "licenseUrl": "https://openfontlicense.org",
    },
    {
        "name": "Noto Sans Devanagari",
        "package": "@fontsource-variable/noto-sans-devanagari",
        "version": "5.3.0",
        "license": OFL,
        "licenseUrl": "https://openfontlicense.org",
    },
)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_manifest(directory: Path = SOURCE_DIRECTORY) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for served in sorted(SERVED_FILES, key=lambda item: item.path):
        data = (directory / served.source).read_bytes()
        files.append(
            {
                "path": served.path,
                "source": served.source,
                "contentType": served.content_type,
                "size": len(data),
                "sha256": sha256_hex(data),
            }
        )
    return {"runtime": RUNTIME_VERSION, "components": list(COMPONENTS), "files": files}


def write_manifest(directory: Path = SOURCE_DIRECTORY) -> Path:
    target = directory / MANIFEST_NAME
    target.write_text(json.dumps(build_manifest(directory), indent=2) + "\n", encoding="utf-8", newline="\n")
    return target


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    directory = Path(arguments[0]).resolve() if arguments else SOURCE_DIRECTORY
    target = write_manifest(directory)
    sys.stdout.write(f"{target}\n")
    return 0
