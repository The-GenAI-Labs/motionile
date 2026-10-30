from dataclasses import dataclass
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from motionile.engine.ai.base import AiModel
from motionile.engine.ai.guardrails.policy import POLICY_MESSAGES, PolicyCode


class GuardDecision(AiModel):
    verdict: Literal["allow", "refuse"]
    code: PolicyCode | None = None
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""
    detected: Annotated[list[PolicyCode], Field(max_length=12)] = Field(default_factory=list[PolicyCode])

    @model_validator(mode="after")
    def code_matches_verdict(self) -> Self:
        if self.verdict == "allow" and self.code is not None:
            raise ValueError("an allowed request carries no code")
        if self.verdict == "refuse" and self.code is None:
            raise ValueError("a refusal carries a policy code")
        return self


@dataclass(frozen=True, slots=True)
class GuardResult:
    allowed: bool
    code: PolicyCode | None = None
    message: str | None = None

    @classmethod
    def allow(cls) -> "GuardResult":
        return cls(allowed=True)

    @classmethod
    def refuse(cls, code: PolicyCode) -> "GuardResult":
        return cls(allowed=False, code=code, message=POLICY_MESSAGES[code])
