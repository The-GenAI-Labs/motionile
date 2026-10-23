import asyncio
import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from motionile.core.config import Settings
from motionile.modules.media.exceptions import GoldenNotFoundError
from motionile.modules.media.render_options import SceneScript

COMPOSITION_FILE = "composition.html"
NARRATION_FILE = "narration.json"
MAX_GOLDEN_BYTES = 4 * 1024 * 1024
TITLE_PATTERN = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
DESCRIPTIONS: dict[str, str] = {
    "kinetic-typography": "Words appearing in sync with narration (ctx.at)",
    "flow-diagram": "A diagram that builds one step at a time, SVG draw",
    "code-walkthrough": "Code with line highlighting following the narration",
    "data-structure": "An array or tree operation animated step by step",
    "comparison-split": "A split-screen comparison that stacks in portrait",
    "css-animation-scene": "CSS animation and transitions driven by the frozen clock",
    "responsive-scene": "One scene that is laid out correctly in all three aspects",
}
DEFAULT_RELATIVE = Path("tests") / "fixtures" / "compositions"
SERVER_ROOT = Path(__file__).resolve().parents[4]


def golden_directory(settings: Settings) -> Path:
    return settings.render.golden_directory or SERVER_ROOT / DEFAULT_RELATIVE


@dataclass(frozen=True, slots=True)
class GoldenComposition:
    name: str
    title: str
    description: str
    language: str
    scenes: tuple[SceneScript, ...]
    html: str


def read_text(path: Path) -> str:
    if path.stat().st_size > MAX_GOLDEN_BYTES:
        raise GoldenNotFoundError
    return path.read_text(encoding="utf-8")


def parse_golden(name: str, directory: Path) -> GoldenComposition:
    document = read_text(directory / COMPOSITION_FILE)
    narration: dict[str, Any] = json.loads(read_text(directory / NARRATION_FILE))
    found = TITLE_PATTERN.search(document)
    title = html.unescape(found.group(1)).strip() if found else name
    return GoldenComposition(
        name=name,
        title=title,
        description=DESCRIPTIONS.get(name, title),
        language=str(narration.get("language", "en")),
        scenes=tuple(
            SceneScript(scene_id=str(item["sceneId"]), text=str(item["text"])) for item in narration["scenes"]
        ),
        html=document,
    )


def list_names(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        return {}
    resolved_root = root.resolve()
    names: dict[str, Path] = {}
    for child in sorted(root.iterdir()):
        resolved = child.resolve()
        if (
            child.is_dir()
            and resolved.is_relative_to(resolved_root)
            and (resolved / COMPOSITION_FILE).is_file()
            and (resolved / NARRATION_FILE).is_file()
        ):
            names[child.name] = resolved
    return names


class GoldenCatalog:
    def __init__(self, root: Path) -> None:
        self._root = root

    async def names(self) -> list[str]:
        return list(await asyncio.to_thread(list_names, self._root))

    async def compositions(self) -> list[GoldenComposition]:
        return await asyncio.to_thread(self._load_all)

    async def load(self, name: str) -> GoldenComposition:
        return await asyncio.to_thread(self._load_one, name)

    def _load_all(self) -> list[GoldenComposition]:
        return [parse_golden(name, directory) for name, directory in list_names(self._root).items()]

    def _load_one(self, name: str) -> GoldenComposition:
        directory = list_names(self._root).get(name)
        if directory is None:
            raise GoldenNotFoundError
        return parse_golden(name, directory)
