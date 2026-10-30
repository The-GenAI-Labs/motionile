import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Final

import yaml
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

from motionile.engine.ai.job_options import SLUG_PATTERN
from motionile.engine.ai.ports import SkillLayer
from motionile.engine.ai.prompts.loader import normalize_body
from motionile.engine.ai.scenes.style_tokens import STYLE_TOKEN_SETS, StyleTokenError, parse_style_tokens

LIBRARY_ROOT: Final = Path(__file__).parent / "library"
SKILL_FILE_NAME: Final = "SKILL.md"
MAX_SLUG_LENGTH: Final = 64
MAX_DESCRIPTION_LENGTH: Final = 1024
MAX_TITLE_LENGTH: Final = 64
CHARACTERS_PER_TOKEN: Final = 4
FRONTMATTER: Final = re.compile(r"\A---\n(?P<frontmatter>.*?)\n---\n(?P<body>.*)\Z", re.DOTALL)
TITLE: Final = re.compile(r"^# (?P<title>.+)$", re.MULTILINE)
LAYER_ORDER: Final[tuple[SkillLayer, ...]] = (SkillLayer.STYLE, SkillLayer.VISUAL, SkillLayer.DOMAIN)

SHIPPED_SKILLS: Final[Mapping[SkillLayer, tuple[str, ...]]] = MappingProxyType(
    {
        SkillLayer.STYLE: ("minimal-dark", "whiteboard", "blueprint", "terminal", "editorial-light"),
        SkillLayer.VISUAL: (
            "kinetic-typography",
            "flow-diagram",
            "architecture-build-up",
            "code-walkthrough",
            "data-structure-operations",
            "comparison-split",
            "timeline-sequence",
            "math-equation",
            "data-chart-story",
            "concept-metaphor",
        ),
        SkillLayer.DOMAIN: (
            "system-design",
            "backend",
            "frontend",
            "devops",
            "applied-ai",
            "machine-learning",
            "blockchain-web3",
            "cybersecurity",
            "concepts",
            "mathematics",
            "physics",
            "chemistry",
            "biology",
            "cs-fundamentals",
            "economics",
        ),
    }
)
MAX_FILE_CHARACTERS: Final[Mapping[SkillLayer, int]] = MappingProxyType(
    {SkillLayer.STYLE: 3_600, SkillLayer.VISUAL: 12_000, SkillLayer.DOMAIN: 7_200}
)

type SkillName = Annotated[str, StringConstraints(pattern=SLUG_PATTERN, max_length=MAX_SLUG_LENGTH)]
type SkillDescription = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_DESCRIPTION_LENGTH)
]


class SkillLibraryError(Exception):
    def __init__(self, problems: tuple[str, ...]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class SkillMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    layer: SkillLayer
    tokens: str | None = None


class SkillFrontmatter(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: SkillName
    description: SkillDescription
    metadata: SkillMetadata


@dataclass(frozen=True, slots=True)
class SkillDocument:
    slug: str
    name: str
    description: str
    layer: SkillLayer
    tokens: str
    body: str
    checksum: bytes
    token_count: int
    frontmatter: Mapping[str, object]
    characters: int

    @property
    def is_style(self) -> bool:
        return self.layer is SkillLayer.STYLE


def token_count_for(characters: int) -> int:
    return characters // CHARACTERS_PER_TOKEN


def token_count_of(body: str) -> int:
    return token_count_for(len(body))


def split_source(text: str, origin: str) -> tuple[object, str]:
    match = FRONTMATTER.match(text)
    if match is None:
        raise SkillLibraryError((f"{origin}: the file must start with a frontmatter block",))
    try:
        raw = yaml.safe_load(match["frontmatter"])
    except yaml.YAMLError as error:
        raise SkillLibraryError((f"{origin}: the frontmatter is not valid YAML",)) from error
    return raw, match["body"]


def parse_frontmatter(raw: object, origin: str) -> SkillFrontmatter:
    try:
        return SkillFrontmatter.model_validate(raw)
    except ValidationError as error:
        problems = tuple(
            f"{origin}: frontmatter {'.'.join(str(part) for part in item['loc']) or '(root)'}: {item['msg']}"
            for item in error.errors(include_url=False, include_context=False, include_input=False)
        )
        raise SkillLibraryError(problems) from error


def token_problems(frontmatter: SkillFrontmatter, origin: str) -> list[str]:
    tokens = frontmatter.metadata.tokens
    if frontmatter.metadata.layer is not SkillLayer.STYLE:
        return [f"{origin}: only style skills carry metadata.tokens"] if tokens is not None else []
    if tokens is None:
        return [f"{origin}: a style skill needs metadata.tokens"]
    try:
        parsed = parse_style_tokens(tokens, slug=frontmatter.name)
    except StyleTokenError as error:
        return [f"{origin}: metadata.tokens: {problem}" for problem in error.problems]
    shipped = STYLE_TOKEN_SETS.get(frontmatter.name)
    if shipped is not None and dict(shipped.properties) != dict(parsed.properties):
        return [f"{origin}: metadata.tokens differ from the style token set shipped for {frontmatter.name}"]
    return []


def structure_problems(
    frontmatter: SkillFrontmatter, title: str | None, characters: int, folder_layer: SkillLayer, folder_name: str
) -> list[str]:
    origin = f"{folder_layer.value}/{folder_name}"
    problems: list[str] = []
    if frontmatter.name != folder_name:
        problems.append(f"{origin}: name {frontmatter.name} must equal the folder name {folder_name}")
    if frontmatter.metadata.layer is not folder_layer:
        problems.append(f"{origin}: metadata.layer {frontmatter.metadata.layer.value} must equal {folder_layer.value}")
    limit = MAX_FILE_CHARACTERS[folder_layer]
    if characters > limit:
        problems.append(f"{origin}: {characters} characters exceed the {folder_layer.value} limit of {limit}")
    if title is None:
        problems.append(f"{origin}: the body needs a level-1 title")
    elif len(title) > MAX_TITLE_LENGTH:
        problems.append(f"{origin}: the title exceeds {MAX_TITLE_LENGTH} characters")
    problems.extend(token_problems(frontmatter, origin))
    return problems


def parse_skill_document(text: str, *, folder_layer: SkillLayer, folder_name: str) -> SkillDocument:
    origin = f"{folder_layer.value}/{folder_name}"
    normalized = normalize_body(text)
    raw, body = split_source(normalized, origin)
    frontmatter = parse_frontmatter(raw, origin)
    heading = TITLE.search(body)
    title = heading["title"].strip() if heading is not None else None
    problems = structure_problems(frontmatter, title, len(normalized), folder_layer, folder_name)
    if problems or title is None:
        raise SkillLibraryError(tuple(problems))
    document_body = body.strip("\n") + "\n"
    return SkillDocument(
        slug=frontmatter.name,
        name=title,
        description=frontmatter.description,
        layer=frontmatter.metadata.layer,
        tokens=(frontmatter.metadata.tokens or "").strip(),
        body=document_body,
        checksum=hashlib.sha256(normalized.encode("utf-8")).digest(),
        token_count=token_count_of(document_body),
        frontmatter=MappingProxyType(frontmatter.model_dump(mode="json", exclude_none=True)),
        characters=len(normalized),
    )


def folder_problems(root: Path) -> list[str]:
    problems: list[str] = []
    layer_names = {layer.value for layer in SkillLayer}
    for entry in sorted(root.iterdir()):
        if entry.name not in layer_names or not entry.is_dir():
            problems.append(f"{entry.name}: only the style, visual and domain folders may sit in the library")
            continue
        for skill_folder in sorted(entry.iterdir()):
            files = sorted(path.name for path in skill_folder.iterdir()) if skill_folder.is_dir() else []
            if files != [SKILL_FILE_NAME]:
                problems.append(f"{entry.name}/{skill_folder.name}: the folder must hold only {SKILL_FILE_NAME}")
    return problems


def membership_problems(documents: list[SkillDocument]) -> list[str]:
    problems: list[str] = []
    slugs = [document.slug for document in documents]
    for slug in sorted({slug for slug in slugs if slugs.count(slug) > 1}):
        problems.append(f"{slug}: the slug exists in more than one layer")
    for layer, expected in SHIPPED_SKILLS.items():
        present = {document.slug for document in documents if document.layer is layer}
        for slug in sorted(set(expected) - present):
            problems.append(f"{layer.value}/{slug}: the shipped skill is missing")
        for slug in sorted(present - set(expected)):
            problems.append(f"{layer.value}/{slug}: the skill is not in the shipped list")
    return problems


def load_library(root: Path = LIBRARY_ROOT) -> tuple[SkillDocument, ...]:
    problems = folder_problems(root)
    documents: list[SkillDocument] = []
    for layer in LAYER_ORDER:
        layer_root = root / layer.value
        if not layer_root.is_dir():
            continue
        for skill_folder in sorted(path for path in layer_root.iterdir() if (path / SKILL_FILE_NAME).is_file()):
            text = (skill_folder / SKILL_FILE_NAME).read_text(encoding="utf-8")
            try:
                documents.append(parse_skill_document(text, folder_layer=layer, folder_name=skill_folder.name))
            except SkillLibraryError as error:
                problems.extend(error.problems)
    problems.extend(membership_problems(documents))
    if problems:
        raise SkillLibraryError(tuple(problems))
    return tuple(documents)
