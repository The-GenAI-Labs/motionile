from enum import StrEnum
from typing import Final
from uuid import UUID

from pydantic import JsonValue

from motionile.engine.ai.graphs.deps import PipelineDependencies
from motionile.engine.ai.graphs.stages import Stage
from motionile.engine.ai.ports import EventPayload, JobEventDraft


class EventType(StrEnum):
    STAGE_STARTED = "stage.started"
    STAGE_COMPLETED = "stage.completed"
    GUARD_PASSED = "guard.passed"
    CONTEXT_READY = "context.ready"
    STORYBOARD_READY = "storyboard.ready"
    CRITIQUE_COMPLETED = "critique.completed"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_GRANTED = "approval.granted"
    SCENE_VOICED = "scene.voiced"
    SCENE_GENERATED = "scene.generated"
    SCENE_REPAIRED = "scene.repaired"
    SCENE_FALLBACK = "scene.fallback"
    VALIDATION_COMPLETED = "validation.completed"
    REVIEW_COMPLETED = "review.completed"
    RENDER_PROGRESS = "render.progress"


ALLOWED_PAYLOAD_KEYS: Final[dict[EventType, frozenset[str]]] = {
    EventType.STAGE_STARTED: frozenset({"stage"}),
    EventType.STAGE_COMPLETED: frozenset({"stage", "durationMs"}),
    EventType.GUARD_PASSED: frozenset(),
    EventType.CONTEXT_READY: frozenset({"skills"}),
    EventType.STORYBOARD_READY: frozenset({"version", "sceneCount"}),
    EventType.CRITIQUE_COMPLETED: frozenset({"revised", "blockingIssues"}),
    EventType.APPROVAL_REQUESTED: frozenset({"version", "expiresAt"}),
    EventType.APPROVAL_GRANTED: frozenset({"version"}),
    EventType.SCENE_VOICED: frozenset({"sceneId", "durationMs"}),
    EventType.SCENE_GENERATED: frozenset({"sceneId"}),
    EventType.SCENE_REPAIRED: frozenset({"sceneId", "attempt", "issueCodes"}),
    EventType.SCENE_FALLBACK: frozenset({"sceneId", "reason"}),
    EventType.VALIDATION_COMPLETED: frozenset({"errors", "warnings"}),
    EventType.REVIEW_COMPLETED: frozenset({"issues"}),
    EventType.RENDER_PROGRESS: frozenset({"renderId", "stage", "progress"}),
}


class FallbackReason(StrEnum):
    REPAIRS_EXHAUSTED = "repairs_exhausted"
    MODEL_OUTPUT_INVALID = "model_output_invalid"


class UnexpectedEventPayloadError(ValueError):
    pass


def draft(event: EventType, stage: Stage, payload: EventPayload | None, *, persist: bool = True) -> JobEventDraft:
    values: dict[str, JsonValue] = dict(payload or {})
    unexpected = set(values) - ALLOWED_PAYLOAD_KEYS[event]
    if unexpected:
        raise UnexpectedEventPayloadError(f"{event.value} does not carry {sorted(unexpected)}")
    return JobEventDraft(type=event.value, stage=stage.value, payload=values, persist=persist)


async def emit(
    deps: PipelineDependencies,
    job_id: UUID,
    event: EventType,
    stage: Stage,
    payload: EventPayload | None = None,
) -> None:
    await deps.store.emit(job_id, draft(event, stage, payload))


async def emit_progress(deps: PipelineDependencies, job_id: UUID, payload: EventPayload, *, persist: bool) -> None:
    await deps.store.emit(job_id, draft(EventType.RENDER_PROGRESS, Stage.RENDER, payload, persist=persist))
