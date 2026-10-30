from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, model_validator

from motionile.engine.ai.base import AiModel


class ApprovalKind(StrEnum):
    APPROVE = "approve"
    REGENERATE = "regenerate"


class ApprovalResume(AiModel):
    kind: ApprovalKind
    instructions: Annotated[str, Field(min_length=1, max_length=2000)] | None = None

    @model_validator(mode="after")
    def instructions_only_for_regeneration(self) -> Self:
        if self.kind is ApprovalKind.APPROVE and self.instructions is not None:
            raise ValueError("an approval carries no instructions")
        return self

    @classmethod
    def approve(cls) -> Self:
        return cls(kind=ApprovalKind.APPROVE)

    @classmethod
    def regenerate(cls, instructions: str | None = None) -> Self:
        return cls(kind=ApprovalKind.REGENERATE, instructions=instructions)
