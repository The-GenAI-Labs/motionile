from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.render.models import Aspect, ValidationReport
from motionile.modules.media.domain import RenderFailureCode, RenderStage
from motionile.modules.media.pipeline.context import (
    FRAMES_FIELD,
    VALIDATION_REPORT,
    PipelineDeps,
    RenderRun,
    StageResult,
)
from motionile.modules.media.pipeline.failures import RenderFailedError, listed
from motionile.modules.media.pipeline.ports import BrowserValidation, CaptureJob, RenderBrowser
from motionile.modules.media.pipeline.reports import report_bytes, report_from_bytes, report_payload

REPORT_NAME = "report.json"
JSON_CONTENT_TYPE = "application/json"
SEGMENT_CONTENT_TYPE = "video/mp4"
PLAN_METADATA = "plan"


def segment_key(run: RenderRun, aspect: Aspect, index: int) -> str:
    return run.workspace.key("segments", aspect.label, f"{index:05d}.mp4")


def frame_progress(run: RenderRun, position: int, aspect_count: int) -> Callable[[int, int], Awaitable[None]]:
    async def report(done: int, total: int) -> None:
        await run.progress.update(RenderStage.CAPTURING, (position + done / max(total, 1)) / aspect_count)

    return report


@dataclass(frozen=True)
class AspectJob:
    aspect: Aspect
    position: int
    html: str
    narration: NarrationDocument


class CapturingStage:
    stage = RenderStage.CAPTURING

    def __init__(self, deps: PipelineDeps) -> None:
        self._deps = deps

    async def execute(self, run: RenderRun) -> StageResult:
        narration = await run.load_narration()
        html = await run.load_clean_html()
        aspects = run.options.engine_aspects
        totals: dict[str, int] = {}
        async with run.toolchain.browser() as browser:
            report = await self._validated(run, browser, html, narration, aspects)
            for position, aspect in enumerate(aspects):
                totals[aspect.label] = await self._capture(run, browser, AspectJob(aspect, position, html, narration))
        return StageResult(
            keys={VALIDATION_REPORT: run.workspace.key(REPORT_NAME)},
            data={FRAMES_FIELD: totals},
            columns={"validation_report": report_payload(report)},
        )

    async def _validated(
        self,
        run: RenderRun,
        browser: RenderBrowser,
        html: str,
        narration: NarrationDocument,
        aspects: list[Aspect],
    ) -> ValidationReport:
        key = run.workspace.key(REPORT_NAME)
        if await run.workspace.exists(key):
            return report_from_bytes(await run.workspace.get_bytes(key))
        await run.checkpoint()
        found = await browser.validate(BrowserValidation(html, narration, aspects, run.seed, run.cancel.requested))
        report = ValidationReport.merge(await run.load_sanitize_report(), found)
        async with self._deps.transaction() as session:
            await self._deps.store_factory(session).set_validation_report(run.render_id, report_payload(report))
        if report.errors:
            message = f"The composition failed validation: {listed(issue.code for issue in report.errors)}."
            raise RenderFailedError(RenderFailureCode.VALIDATION_FAILED, message, report=report)
        await run.workspace.put_bytes(key, report_bytes(report), JSON_CONTENT_TYPE)
        return report

    async def _capture(self, run: RenderRun, browser: RenderBrowser, job: AspectJob) -> int:
        aspect, narration = job.aspect, job.narration
        segment_directory = run.workspace.path("segments")
        plan = run.toolchain.plan_segments(narration, aspect, segment_directory)
        completed: set[int] = set()
        for index in range(len(plan.segments)):
            info = await run.workspace.head(segment_key(run, aspect, index))
            if info is not None and info.metadata.get(PLAN_METADATA) == plan.fingerprint:
                completed.add(index)

        async def uploaded(index: int, path: Path | None) -> None:
            if path is not None:
                await run.workspace.put_file(
                    segment_key(run, aspect, index),
                    path,
                    SEGMENT_CONTENT_TYPE,
                    metadata={PLAN_METADATA: plan.fingerprint},
                )

        await browser.capture(
            CaptureJob(
                html=job.html,
                narration=narration,
                aspect=aspect,
                seed=run.seed,
                segment_directory=segment_directory,
                completed_chunks=frozenset(completed),
                on_segment=uploaded,
                on_progress=frame_progress(run, job.position, len(run.options.aspects)),
                should_cancel=run.cancel.requested,
            )
        )
        return plan.total_frames
