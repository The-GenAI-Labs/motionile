from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from motionile.core.schemas import ResponseModel, StrictModel
from motionile.modules.platform.registry import SettingValue


class SettingResponse(ResponseModel):
    key: str
    value: SettingValue
    schema_: dict[str, object] = Field(serialization_alias="schema", validation_alias="schema")
    description: str
    public: bool
    version: int
    updated_at: datetime | None = None


class SettingUpdateRequest(StrictModel):
    value: SettingValue
    version: int = Field(ge=1)


class PublicSettingsResponse(ResponseModel):
    settings: dict[str, SettingValue]


class FlagRule(StrictModel):
    kind: Literal["user", "role"]
    values: list[str] = Field(min_length=1, max_length=100)


class FeatureFlagResponse(ResponseModel):
    key: str
    description: str | None
    enabled: bool
    rollout_percentage: int
    rules: list[FlagRule]
    version: int
    updated_at: datetime


class FeatureFlagWriteRequest(StrictModel):
    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
    description: str | None = Field(default=None, max_length=500)
    enabled: bool = False
    rollout_percentage: int = Field(default=0, ge=0, le=100)
    rules: list[FlagRule] = Field(default_factory=list[FlagRule], max_length=20)

    @model_validator(mode="after")
    def unique_rules(self) -> "FeatureFlagWriteRequest":
        pairs = [(rule.kind, value) for rule in self.rules for value in rule.values]
        if len(pairs) != len(set(pairs)):
            raise ValueError("Feature flag rules must be unique.")
        for rule in self.rules:
            if rule.kind == "user":
                for value in rule.values:
                    UUID(value)
        return self


class FeatureFlagUpdateRequest(StrictModel):
    description: str | None = Field(default=None, max_length=500)
    enabled: bool
    rollout_percentage: int = Field(ge=0, le=100)
    rules: list[FlagRule] = Field(default_factory=list[FlagRule], max_length=20)
    version: int = Field(ge=1)


class FeatureFlagDeleteRequest(StrictModel):
    version: int = Field(ge=1)


class EvaluatedFlagsResponse(ResponseModel):
    flags: dict[str, bool]
