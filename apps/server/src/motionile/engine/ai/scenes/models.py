import re
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from motionile.engine.ai.base import AiModel
from motionile.engine.ai.job_options import SceneIdentifier

SCENE_MODULE_VERSION: Literal[1] = 1
SCENE_ROOT_CLASS_PREFIX = "mo-s-"
ASSET_ID_PATTERN = r"^[a-z][a-z0-9-]{0,31}$"
MAX_BUILDER_CHARS = 20_000
MAX_CSS_CHARS = 20_000
MAX_ASSET_CHARS = 60_000
MAX_ASSETS = 8
MAX_MODULE_CHARS = 120_000

type BuilderBody = Annotated[str, StringConstraints(min_length=1, max_length=MAX_BUILDER_CHARS)]
type ScopedCss = Annotated[str, StringConstraints(max_length=MAX_CSS_CHARS)]
type AssetIdentifier = Annotated[str, StringConstraints(pattern=ASSET_ID_PATTERN)]


def scene_root_class(scene_id: str) -> str:
    return f"{SCENE_ROOT_CLASS_PREFIX}{scene_id}"


class SceneAsset(AiModel):
    id: AssetIdentifier
    svg: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_ASSET_CHARS)]


class SceneModule(AiModel):
    version: Literal[1] = SCENE_MODULE_VERSION
    scene_id: SceneIdentifier
    builder: BuilderBody
    css: ScopedCss = ""
    assets: Annotated[list[SceneAsset], Field(max_length=MAX_ASSETS)] = Field(default_factory=list[SceneAsset])

    @model_validator(mode="after")
    def assets_are_unique_and_bounded(self) -> "SceneModule":
        identifiers = [asset.id for asset in self.assets]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("asset IDs must be unique")
        total = len(self.builder) + len(self.css) + sum(len(asset.svg) for asset in self.assets)
        if total > MAX_MODULE_CHARS:
            raise ValueError(f"a scene module may hold at most {MAX_MODULE_CHARS} characters")
        return self

    @property
    def root_class(self) -> str:
        return scene_root_class(self.scene_id)


class StaticFindingCode(StrEnum):
    BUILDER_SYNTAX = "builder_syntax"
    BUILDER_IDENTIFIER = "builder_identifier"
    BUILDER_FORBIDDEN_SYNTAX = "builder_forbidden_syntax"
    CSS_SYNTAX = "css_syntax"
    CSS_UNSCOPED = "css_unscoped"
    CSS_FORBIDDEN = "css_forbidden"
    ASSET_INVALID = "asset_invalid"
    MODULE_TOO_LARGE = "module_too_large"


class StaticFinding(AiModel):
    code: StaticFindingCode
    message: str
    line: int | None = None
    detail: str | None = None


ROOT_CLASS_PATTERN = re.compile(rf"^{re.escape(SCENE_ROOT_CLASS_PREFIX)}[a-z][a-z0-9-]{{0,31}}$")
