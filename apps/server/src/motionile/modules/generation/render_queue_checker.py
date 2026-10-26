from collections.abc import Sequence
from uuid import UUID

from pydantic import JsonValue

from motionile.engine.ai.ports import CompositionCheck, CompositionIssue, SampledFrame
from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.render.models import Aspect, InvalidCompositionError, ValidationIssue, ValidationReport
from motionile.modules.generation.ports import CompositionCheckGateway
from motionile.modules.media import CompositionCheckRequest

SELECTOR_KEY = "selector"


def issue_of(issue: ValidationIssue) -> CompositionIssue:
    detail: dict[str, JsonValue] = dict(issue.detail)
    if issue.selector is not None:
        detail[SELECTOR_KEY] = issue.selector
    return CompositionIssue(
        code=issue.code,
        severity=issue.severity,
        kind=issue.kind,
        message=issue.message,
        scene_id=issue.scene,
        aspect=issue.aspect,
        time_ms=issue.time_ms,
        detail=detail,
    )


def report_summary(report: ValidationReport) -> dict[str, JsonValue]:
    return {"version": report.version, "stats": report.stats.model_dump(mode="json", by_alias=True)}


class RenderQueueChecker:
    def __init__(self, job_id: UUID, gateway: CompositionCheckGateway) -> None:
        self._job_id = job_id
        self._gateway = gateway

    def _request(
        self, html: str, narration: NarrationDocument, aspects: Sequence[str], *, want_frames: bool
    ) -> CompositionCheckRequest:
        return CompositionCheckRequest(
            html=html,
            narration=narration,
            aspects=tuple(Aspect(aspect) for aspect in aspects),
            want_frames=want_frames,
        )

    async def check(self, html: str, narration: NarrationDocument, aspects: Sequence[str]) -> CompositionCheck:
        outcome = await self._gateway.run(self._job_id, self._request(html, narration, aspects, want_frames=False))
        return CompositionCheck(
            valid=outcome.report.valid,
            issues=tuple(issue_of(issue) for issue in outcome.report.issues),
            report=report_summary(outcome.report),
        )

    async def sample_frames(
        self, html: str, narration: NarrationDocument, aspects: Sequence[str]
    ) -> list[SampledFrame]:
        outcome = await self._gateway.run(self._job_id, self._request(html, narration, aspects, want_frames=True))
        if not outcome.frames and outcome.report.errors:
            raise InvalidCompositionError(outcome.report.errors)
        return [
            SampledFrame(scene_id=frame.scene_id, aspect=frame.aspect, time_ms=frame.time_ms, png=frame.png)
            for frame in outcome.frames
        ]
