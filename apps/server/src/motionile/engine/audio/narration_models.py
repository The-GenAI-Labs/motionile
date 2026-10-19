from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

NARRATION_VERSION: Literal[1] = 1


class NarrationModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
        extra="forbid",
        frozen=True,
    )


class NarrationWord(NarrationModel):
    index: int = Field(ge=0)
    text: str = Field(min_length=1)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    scene_start_ms: int = Field(ge=0)
    scene_end_ms: int = Field(ge=0)


class NarrationScene(NarrationModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    index: int = Field(ge=0)
    start_ms: int = Field(ge=0)
    duration_ms: int = Field(gt=0)
    text: str
    words: tuple[NarrationWord, ...]

    @property
    def end_ms(self) -> int:
        return self.start_ms + self.duration_ms


class NarrationDocument(NarrationModel):
    version: Literal[1] = NARRATION_VERSION
    total_duration_ms: int = Field(ge=0)
    scenes: tuple[NarrationScene, ...]

    def window_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)
