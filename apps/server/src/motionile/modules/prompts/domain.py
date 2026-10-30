import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final
from uuid import UUID

from motionile.modules.audit import AuditContext

MAX_BODY_CHARS: Final = 60_000
MAX_VARIABLES: Final = 32
MAX_RUN_VERSIONS: Final = 20
MAX_VERSION_NUMBER: Final = 2_147_483_647
MINIMUM_HISTORY: Final = 2
CHECKSUM_PREFIX_CHARS: Final = 12
TEMPLATE_KEY_PATTERN: Final = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"
SUITE_PATTERN: Final = r"^[a-z][a-z0-9_.-]{0,59}$"
DATASET_VERSION_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$"
ERROR_CODE_PATTERN: Final = r"^[a-z][a-z0-9_]{1,59}$"
VARIABLE_PATTERN: Final = r"^[a-z][a-z0-9_]*$"
PENDING_DATASET_VERSION: Final = "pending"
AUDIT_TEMPLATE_TARGET: Final = "prompt_template"
AUDIT_RUN_TARGET: Final = "eval_run"

SUITE_FORMAT = re.compile(SUITE_PATTERN)
DATASET_VERSION_FORMAT = re.compile(DATASET_VERSION_PATTERN)
ERROR_CODE_FORMAT = re.compile(ERROR_CODE_PATTERN)


class EvalStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class RunStatus(StrEnum):
    RUNNING = "running"
    FINISHED = "finished"
    ERRORED = "errored"


class RunTrigger(StrEnum):
    CI = "ci"
    NIGHTLY = "nightly"
    ADMIN = "admin"


class EvalQueue(StrEnum):
    GENERATION = "generation"
    BROWSER = "render"


EVAL_QUEUE_BY_SUITE: Final[Mapping[str, EvalQueue]] = {
    "planner": EvalQueue.GENERATION,
    "safety": EvalQueue.GENERATION,
    "cost": EvalQueue.GENERATION,
    "scenes": EvalQueue.BROWSER,
    "sync": EvalQueue.BROWSER,
}


class ActivationKind(StrEnum):
    ACTIVATED = "activated"
    ROLLED_BACK = "rolled_back"


class PromptAction(StrEnum):
    DRAFT_CREATED = "prompts.draft_created"
    VERSION_ACTIVATED = "prompts.version_activated"
    VERSION_ROLLED_BACK = "prompts.version_rolled_back"
    EVAL_STARTED = "prompts.eval_started"
    EVAL_RECORDED = "prompts.eval_recorded"
    DIFF_VIEWED = "prompts.diff_viewed"


ACTIVATION_ACTIONS: Final[Mapping[ActivationKind, PromptAction]] = {
    ActivationKind.ACTIVATED: PromptAction.VERSION_ACTIVATED,
    ActivationKind.ROLLED_BACK: PromptAction.VERSION_ROLLED_BACK,
}
KIND_BY_ACTION: Final[Mapping[str, ActivationKind]] = {
    action.value: kind for kind, action in ACTIVATION_ACTIONS.items()
}


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: UUID
    context: AuditContext


@dataclass(frozen=True, slots=True)
class Subject:
    type: str
    id: UUID


@dataclass(frozen=True, slots=True)
class Activation:
    kind: ActivationKind
    actor: Actor | None
    extra: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ActivationEvent:
    kind: ActivationKind
    from_version_id: UUID | None
    to_version_id: UUID


def optional_uuid(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def activation_event_of(action: str, metadata: Mapping[str, Any]) -> ActivationEvent | None:
    kind = KIND_BY_ACTION.get(action)
    to_version_id = optional_uuid(metadata.get("version_id"))
    if kind is None or to_version_id is None:
        return None
    return ActivationEvent(kind, optional_uuid(metadata.get("from_version_id")), to_version_id)


def previous_version_id(events: list[ActivationEvent], current: UUID) -> UUID | None:
    history: list[UUID] = []
    for event in events:
        if event.kind is ActivationKind.ACTIVATED:
            history.append(event.to_version_id)
        elif history and history[-1] == event.from_version_id:
            history.pop()
    if len(history) >= MINIMUM_HISTORY and history[-1] == current:
        return history[-2]
    return None
