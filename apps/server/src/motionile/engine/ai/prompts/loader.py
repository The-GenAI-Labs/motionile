import hashlib
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from motionile.engine.ai.prompts.render import CANARY_VARIABLE, PromptRenderError, referenced_variables

PROMPTS_ROOT = Path(__file__).parent
SYSTEM_DIRECTORY = PROMPTS_ROOT / "system"
RUNTIME_REFERENCE_PATH = PROMPTS_ROOT / "runtime_reference.md"
SOURCE_SUFFIX = ".md"

PROMPT_KEYS: tuple[str, ...] = (
    "guard.input",
    "guard.output",
    "router.skills",
    "planner.storyboard",
    "critic.storyboard",
    "scene.module",
    "repair.scene",
    "review.vision",
)

FRONTMATTER = re.compile(r"\A---\n(?P<frontmatter>.*?)\n---\n(?P<body>.*)\Z", re.DOTALL)


class PromptSourceError(Exception):
    pass


class PromptFrontmatter(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: Annotated[str, Field(pattern=r"^[a-z]+(\.[a-z]+)+$", max_length=64)]
    version: Annotated[int, Field(ge=1)]
    variables: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)]]


@dataclass(frozen=True, slots=True)
class PromptSource:
    key: str
    version: int
    variables: tuple[str, ...]
    body: str
    checksum: bytes


def normalize_body(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(lines).strip("\n") + "\n"


def body_checksum(body: str) -> bytes:
    return hashlib.sha256(normalize_body(body).encode("utf-8")).digest()


def parse_prompt_source(text: str, *, origin: str) -> PromptSource:
    match = FRONTMATTER.match(text.replace("\r\n", "\n").replace("\r", "\n"))
    if match is None:
        raise PromptSourceError(f"{origin}: the file must start with a frontmatter block")
    try:
        raw = yaml.safe_load(match["frontmatter"])
        frontmatter = PromptFrontmatter.model_validate(raw)
    except (yaml.YAMLError, ValidationError) as error:
        raise PromptSourceError(f"{origin}: the frontmatter is invalid") from error
    body = normalize_body(match["body"])
    if len(set(frontmatter.variables)) != len(frontmatter.variables):
        raise PromptSourceError(f"{origin}: the variables must be unique")
    try:
        referenced = referenced_variables(body)
    except PromptRenderError as error:
        raise PromptSourceError(f"{origin}: {error}") from error
    declared = frozenset(frontmatter.variables)
    if declared != referenced:
        undeclared = sorted(referenced - declared)
        unused = sorted(declared - referenced)
        raise PromptSourceError(f"{origin}: undeclared variables {undeclared}, unused variables {unused}")
    if CANARY_VARIABLE not in declared:
        raise PromptSourceError(f"{origin}: the prompt must embed the canary")
    return PromptSource(
        key=frontmatter.key,
        version=frontmatter.version,
        variables=tuple(frontmatter.variables),
        body=body,
        checksum=hashlib.sha256(body.encode("utf-8")).digest(),
    )


def load_prompt_source(path: Path) -> PromptSource:
    source = parse_prompt_source(path.read_text(encoding="utf-8"), origin=path.name)
    if path.name != f"{source.key}{SOURCE_SUFFIX}":
        raise PromptSourceError(f"{path.name}: the file name must equal the key")
    return source


def load_prompt_sources(directory: Path = SYSTEM_DIRECTORY) -> tuple[PromptSource, ...]:
    sources = [load_prompt_source(path) for path in sorted(directory.glob(f"*{SOURCE_SUFFIX}"))]
    keys = [source.key for source in sources]
    if len(set(keys)) != len(keys):
        raise PromptSourceError("prompt keys must be unique")
    return tuple(sorted(sources, key=lambda source: source.key))


@cache
def load_runtime_reference() -> str:
    return normalize_body(RUNTIME_REFERENCE_PATH.read_text(encoding="utf-8"))
