import asyncio

from motionile.engine.render.models import ValidationReport
from motionile.engine.render.sanitize import sanitize_composition
from motionile.modules.media.domain import RenderFailureCode, RenderStage
from motionile.modules.media.pipeline.context import (
    CLEAN_COMPOSITION,
    SANITIZE_REPORT,
    PipelineDeps,
    RenderRun,
    StageResult,
)
from motionile.modules.media.pipeline.failures import RenderFailedError, listed
from motionile.modules.media.pipeline.reports import report_bytes, report_payload

CLEAN_NAME = "composition.clean.html"
REPORT_NAME = "report.sanitize.json"
HTML_CONTENT_TYPE = "text/plain"
JSON_CONTENT_TYPE = "application/json"


class PrepareStage:
    stage = RenderStage.PREPARING

    def __init__(self, deps: PipelineDeps) -> None:
        self._deps = deps

    async def execute(self, run: RenderRun) -> StageResult:
        deps = self._deps
        async with deps.transaction() as session:
            asset = await deps.assets.get(session, run.owner_id, run.composition_asset_id)
        html = (await deps.assets.read_bytes(asset)).decode("utf-8")
        await run.checkpoint()
        result = await asyncio.to_thread(sanitize_composition, html, scene_ids=run.options.scene_ids)
        report = ValidationReport(issues=result.findings)
        if result.errors:
            message = f"The composition failed the static checks: {listed(issue.code for issue in result.errors)}."
            raise RenderFailedError(RenderFailureCode.INVALID_COMPOSITION, message, report=report)
        clean_key = run.workspace.key(CLEAN_NAME)
        report_key = run.workspace.key(REPORT_NAME)
        await run.workspace.put_bytes(clean_key, result.html.encode("utf-8"), HTML_CONTENT_TYPE)
        await run.workspace.put_bytes(report_key, report_bytes(report), JSON_CONTENT_TYPE)
        run.clean_html = result.html
        run.sanitize_report = report
        return StageResult(
            keys={CLEAN_COMPOSITION: clean_key, SANITIZE_REPORT: report_key},
            columns={"validation_report": report_payload(report)},
        )
