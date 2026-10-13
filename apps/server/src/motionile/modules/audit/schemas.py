import re
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, IPvAnyAddress, field_validator

ACTION_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
USER_AGENT_LIMIT = 512


class ActorType(StrEnum):
    USER = "user"
    ADMIN = "admin"
    SYSTEM = "system"
    API_KEY = "api_key"


class AuditContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    ip: IPvAnyAddress | None = None
    user_agent: str | None = None
    request_id: str | None = Field(default=None, max_length=64)

    @field_validator("user_agent")
    @classmethod
    def truncate_user_agent(cls, value: str | None) -> str | None:
        return value[:USER_AGENT_LIMIT] if value is not None else None


class AuditEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action: str = Field(min_length=3, max_length=100, pattern=ACTION_PATTERN.pattern)
    actor_type: ActorType
    actor_user_id: UUID | None = None
    target_type: str | None = Field(default=None, max_length=64)
    target_id: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict[str, Any])
