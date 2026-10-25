import re
from dataclasses import dataclass
from typing import Final

from motionile.engine.ai.scenes.models import SceneAsset, SceneModule
from motionile.engine.ai.skills.loader import SkillDocument, SkillLibraryError

EXAMPLE_SCENE_ID: Final = "demo"
EXAMPLE_HEADING: Final = re.compile(r"^#### Example: (?P<title>.+)$")
ANY_HEADING: Final = re.compile(r"^#{1,4} ")
NARRATION_LINE: Final = re.compile(r'^Narration: "(?P<text>.+)"$')
FENCE_OPEN: Final = re.compile(r"^```(?P<language>[a-z]+)(?: id=(?P<asset>[a-z][a-z0-9-]{0,31}))?$")
FENCE_CLOSE: Final = "```"


@dataclass(frozen=True, slots=True)
class SkillExample:
    skill: str
    title: str
    narration: str
    builder: str
    css: str
    assets: tuple[SceneAsset, ...]

    def scene_module(self, scene_id: str = EXAMPLE_SCENE_ID) -> SceneModule:
        return SceneModule(scene_id=scene_id, builder=self.builder, css=self.css, assets=list(self.assets))


@dataclass(frozen=True, slots=True)
class FencedBlock:
    language: str
    asset: str | None
    text: str


def example_sections(body: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    current: tuple[str, list[str]] | None = None
    in_fence = False
    for line in body.split("\n"):
        if line.startswith(FENCE_CLOSE):
            in_fence = not in_fence
        heading = None if in_fence else EXAMPLE_HEADING.match(line)
        if heading is not None:
            current = (heading["title"].strip(), [])
            sections.append(current)
        elif current is not None and not in_fence and ANY_HEADING.match(line):
            current = None
        elif current is not None:
            current[1].append(line)
    return sections


def fenced_blocks(lines: list[str], origin: str) -> list[FencedBlock]:
    blocks: list[FencedBlock] = []
    index = 0
    while index < len(lines):
        opening = FENCE_OPEN.match(lines[index])
        index += 1
        if opening is None:
            continue
        content: list[str] = []
        while index < len(lines) and lines[index] != FENCE_CLOSE:
            content.append(lines[index])
            index += 1
        if index == len(lines):
            raise SkillLibraryError((f"{origin}: a code fence is never closed",))
        index += 1
        blocks.append(FencedBlock(opening["language"], opening["asset"], "\n".join(content)))
    return blocks


def narration_of(lines: list[str], origin: str) -> str:
    matches = [match for line in lines if (match := NARRATION_LINE.match(line)) is not None]
    if len(matches) != 1:
        raise SkillLibraryError((f"{origin}: an example needs exactly one Narration line",))
    return matches[0]["text"]


def single_block(blocks: list[FencedBlock], language: str, origin: str, *, required: bool) -> str:
    found = [block for block in blocks if block.language == language and block.asset is None]
    if len(found) > 1 or (required and not found):
        raise SkillLibraryError(
            (f"{origin}: an example needs {'exactly' if required else 'at most'} one {language} block",)
        )
    return found[0].text if found else ""


def build_example(skill: str, title: str, lines: list[str]) -> SkillExample:
    origin = f"{skill}: example {title!r}"
    blocks = fenced_blocks(lines, origin)
    unknown = sorted({block.language for block in blocks} - {"js", "css", "svg"})
    if unknown:
        raise SkillLibraryError((f"{origin}: unsupported code blocks: {', '.join(unknown)}",))
    assets = tuple(
        SceneAsset(id=block.asset, svg=block.text) for block in blocks if block.language == "svg" and block.asset
    )
    if len(assets) != sum(1 for block in blocks if block.language == "svg"):
        raise SkillLibraryError((f"{origin}: every svg block needs an id",))
    return SkillExample(
        skill=skill,
        title=title,
        narration=narration_of(lines, origin),
        builder=single_block(blocks, "js", origin, required=True),
        css=single_block(blocks, "css", origin, required=False),
        assets=assets,
    )


def extract_examples(document: SkillDocument) -> tuple[SkillExample, ...]:
    return tuple(build_example(document.slug, title, lines) for title, lines in example_sections(document.body))
