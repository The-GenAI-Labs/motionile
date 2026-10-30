from pydantic import JsonValue

from motionile.engine.ai.graphs.deps import PipelineDependencies
from motionile.engine.ai.graphs.errors import PipelineErrorCode, pipeline_error
from motionile.engine.ai.graphs.events import EventType, emit
from motionile.engine.ai.graphs.issues import attribute_issues, blocking_records
from motionile.engine.ai.graphs.stages import Stage
from motionile.engine.ai.graphs.state import PipelineState
from motionile.engine.ai.nodes.common import job_id_of, stage_scope
from motionile.engine.ai.nodes.composition import Composition, load_composition
from motionile.engine.ai.ports import CompositionCheck, CompositionIssue


def ensure_fallbacks_hold(composition: Composition, grouped: dict[str, list[CompositionIssue]]) -> None:
    for scene_id, issues in grouped.items():
        if scene_id in composition.fallback_ids and any(issue.is_blocking for issue in issues):
            raise pipeline_error(PipelineErrorCode.COMPOSITION_INVALID, f"scene {scene_id}")


def validation_report(check: CompositionCheck) -> dict[str, JsonValue]:
    return {
        "valid": check.valid,
        "errors": sum(1 for issue in check.issues if issue.is_blocking),
        "warnings": sum(1 for issue in check.issues if not issue.is_blocking),
        "issues": [
            {
                "code": issue.code,
                "severity": issue.severity,
                "kind": issue.kind,
                "sceneId": issue.scene_id,
                "aspect": issue.aspect,
                "timeMs": issue.time_ms,
                "message": issue.message,
            }
            for issue in check.issues
        ],
        "report": dict(check.report),
    }


async def run_validate(deps: PipelineDependencies, state: PipelineState) -> PipelineState:
    job_id = job_id_of(state)
    async with stage_scope(deps, job_id, Stage.VALIDATE):
        composition = await load_composition(deps, job_id)
        check = await deps.checker.check(composition.html, composition.narration, composition.storyboard.aspects)
        scene_ids = [scene.id for scene in composition.storyboard.scenes]
        targets = [scene_id for scene_id in scene_ids if scene_id not in composition.fallback_ids]
        grouped = attribute_issues(check.issues, scene_ids, targets)
        ensure_fallbacks_hold(composition, grouped)
        if not targets and any(issue.is_blocking and issue.scene_id is None for issue in check.issues):
            raise pipeline_error(PipelineErrorCode.COMPOSITION_INVALID)
        errors = sum(1 for issue in check.issues if issue.is_blocking)
        await emit(
            deps,
            job_id,
            EventType.VALIDATION_COMPLETED,
            Stage.VALIDATE,
            {"errors": errors, "warnings": len(check.issues) - errors},
        )
        await deps.store.save_reports(job_id, validation=validation_report(check), review={})
        return {"issues": blocking_records(grouped)}
