import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from motionile.engine.render.models import RenderEngineError
from motionile.engine.render.runtime.manifest import MANIFEST_NAME, RUNTIME_VERSION, sha256_hex

RUNTIME_ORIGIN = "https://runtime.motionile.local"
RUNTIME_HOST = "runtime.motionile.local"
RUNTIME_BASE_PATH = f"/{RUNTIME_VERSION}/"
RUNTIME_BASE_URL = f"{RUNTIME_ORIGIN}{RUNTIME_BASE_PATH}"
COMPOSITION_PATH = "/composition.html"
COMPOSITION_URL = f"{RUNTIME_ORIGIN}{COMPOSITION_PATH}"
FONT_EXTENSION = ".woff2"
CACHE_CONTROL = "public, max-age=31536000, immutable"


class RuntimeBundleError(RenderEngineError):
    code = "runtime_bundle_invalid"


@dataclass(frozen=True)
class RuntimeAsset:
    path: str
    body: bytes
    content_type: str
    sha256: str

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Content-Type": self.content_type,
            "Cache-Control": CACHE_CONTROL,
            "ETag": f'"{self.sha256}"',
            "Access-Control-Allow-Origin": "*",
            "Cross-Origin-Resource-Policy": "cross-origin",
            "X-Content-Type-Options": "nosniff",
        }


class RuntimeBundle:
    def __init__(self, assets: Mapping[str, RuntimeAsset], manifest: Mapping[str, Any]) -> None:
        self._assets = dict(assets)
        self.manifest = dict(manifest)

    @property
    def version(self) -> str:
        return RUNTIME_VERSION

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(sorted(self._assets))

    def asset(self, path: str) -> RuntimeAsset | None:
        return self._assets.get(path)

    def asset_for_url(self, url: str) -> RuntimeAsset | None:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname != RUNTIME_HOST or parts.port not in (None, 443):
            return None
        if not parts.path.startswith(RUNTIME_BASE_PATH):
            return None
        return self._assets.get(parts.path.removeprefix(RUNTIME_BASE_PATH))

    def font_assets(self) -> tuple[RuntimeAsset, ...]:
        return tuple(asset for asset in self._assets.values() if asset.path.endswith(FONT_EXTENSION))

    def write_fonts(self, directory: Path) -> tuple[Path, ...]:
        directory.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for asset in self.font_assets():
            target = directory / Path(asset.path).name
            target.write_bytes(asset.body)
            written.append(target)
        return tuple(written)


def read_manifest() -> Mapping[str, Any]:
    root = resources.files(__name__).joinpath(RUNTIME_VERSION)
    raw = json.loads(root.joinpath(MANIFEST_NAME).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeBundleError("The runtime manifest is not an object")
    return cast("Mapping[str, Any]", raw)


def load_assets(manifest: Mapping[str, Any]) -> dict[str, RuntimeAsset]:
    root = resources.files(__name__).joinpath(RUNTIME_VERSION)
    assets: dict[str, RuntimeAsset] = {}
    for entry in cast("list[Mapping[str, Any]]", manifest["files"]):
        path = str(entry["path"])
        body = root.joinpath(str(entry["source"])).read_bytes()
        digest = sha256_hex(body)
        if digest != entry["sha256"]:
            raise RuntimeBundleError(f"Runtime file {path} does not match its manifest hash")
        assets[path] = RuntimeAsset(path=path, body=body, content_type=str(entry["contentType"]), sha256=digest)
    return assets


@lru_cache(maxsize=1)
def load_runtime_bundle() -> RuntimeBundle:
    manifest = read_manifest()
    return RuntimeBundle(load_assets(manifest), manifest)
