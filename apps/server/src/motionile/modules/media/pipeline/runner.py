import asyncio
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog

from motionile.engine.render.models import CaptureCancelledError, ValidationReport
from motionile.modules.media.domain import (
    RENDER_PIPELINE,
    RenderFailureCode,
    RenderStage,
    RenderStatus,
    following_status,
    is_terminal,
    require_transition,
)
from motionile.modules.media.models import Render
from motionile.modules.media.pipeline.context import PipelineDeps, RenderRun, Stage, StageResult
from motionile.modules.media.pipeline.failures import RenderFailedError, RenderStateChangedError, classify
from motionile.modules.media.pipeline.progress import CancelWatch, ProgressReporter, stage_base_progress
from motionile.modules.media.pipeline.reports import report_from_payload, report_payload
from motionile.modules.media.pipeline.stages import build_stages
from motionile.modules.media.pipeline.workspace import Workspace
from motionile.modules.media.render_options import RenderOptions
from motionile.modules.media.render_repository import Advance, Finish

STAGE_STATUSES = frozenset(stage.status for stage in RENDER_PIPELINE)
SEED_MASK = 0x7FFFFFFF
MS_PER_SECOND = 1000
CANCELLED_MESSAGE = "The render was cancelled."

logger = structlog.get_logger(__name__)


def seed_for(render_id: UUID) -> int:
    return render_id.int & SEED_MASK


def stage_of(render: Render) -> RenderStage | None:
    return RenderStage(render.stage) if render.stage is not None else None


class RenderPipeline:
    def __init__(self, deps: PipelineDeps, stages: Mapping[RenderStage, Stage] | None = None) -> None:
        self._deps = deps
        self._stages = dict(stages) if stages is not None else build_stages(deps)

    async def run(self, render_id: UUID) -> None:
        deps = self._deps
        async with deps.transaction() as session:
            render = await deps.store_factory(session).get_unscoped(render_id)
        if render is None or is_terminal(RenderStatus(render.status)):
            logger.info("media.render_skipped", render_id=str(render_id))
            return
        options = RenderOptions.model_validate(render.options)
        parent = deps.settings.render.work_directory or Path(tempfile.gettempdir())
        async with Workspace.open(deps.storage, render_id, parent) as workspace:
            progress = ProgressReporter(deps.transaction, deps.store_factory, deps.events, deps.clock, render_id)
            progress.remember(render.progress)
            run = RenderRun(
                render_id=render_id,
                owner_id=render.owner_user_id,
                options=options,
                composition_asset_id=render.composition_asset_id,
                checkpoints=dict(render.checkpoints),
                workspace=workspace,
                progress=progress,
                cancel=CancelWatch(deps.transaction, deps.store_factory, deps.events, render_id),
                seed=seed_for(render_id),
                toolchain=deps.toolchain_for(options.fps),
            )
            await self._guarded(run, RenderStatus(render.status))

    async def _guarded(self, run: RenderRun, status: RenderStatus) -> None:
        try:
            await self._drive(run, status)
        except RenderStateChangedError:
            logger.info("media.render_state_changed", render_id=str(run.render_id))
        except CaptureCancelledError:
            await self._finish(run, RenderStatus.CANCELLED, None)
        except Exception as error:
            failure = classify(error)
            if failure is None:
                raise
            await self._finish(run, RenderStatus.FAILED, failure)

    async def _drive(self, run: RenderRun, status: RenderStatus) -> None:
        if status is RenderStatus.QUEUED:
            await self._begin(run)
            status = RenderStatus.PREPARING
        while status in STAGE_STATUSES:
            status = await self._run_stage(run, RenderStage(status.value))

    async def _begin(self, run: RenderRun) -> None:
        deps = self._deps
        require_transition(RenderStatus.QUEUED, RenderStatus.PREPARING)
        async with deps.transaction() as session:
            row = await deps.store_factory(session).advance(
                run.render_id,
                Advance(
                    RenderStatus.QUEUED,
                    RenderStatus.PREPARING,
                    RenderStage.PREPARING,
                    0,
                    columns={"started_at": deps.clock.now()},
                ),
            )
        if row is None:
            raise RenderStateChangedError
        await run.progress.publish(RenderStatus.PREPARING, RenderStage.PREPARING, 0)

    async def _run_stage(self, run: RenderRun, stage: RenderStage) -> RenderStatus:
        await run.checkpoint()
        loop = asyncio.get_running_loop()
        started = loop.time()
        limit = asyncio.timeout(self._deps.settings.render.stage_timeout_seconds)
        try:
            async with limit, run.progress.heartbeat():
                result = await self._stages[stage].execute(run)
        except TimeoutError:
            run.timings[stage.value] = round((loop.time() - started) * MS_PER_SECOND)
            if limit.expired():
                raise RenderFailedError(
                    RenderFailureCode.TIMEOUT, "The render stage exceeded its time limit."
                ) from None
            raise
        except BaseException:
            run.timings[stage.value] = round((loop.time() - started) * MS_PER_SECOND)
            raise
        elapsed = round((loop.time() - started) * MS_PER_SECOND)
        run.timings[stage.value] = elapsed
        return await self._complete(run, stage, result, elapsed)

    async def _complete(self, run: RenderRun, stage: RenderStage, result: StageResult, elapsed_ms: int) -> RenderStatus:
        deps = self._deps
        target = following_status(stage.status)
        if target is None:
            raise RenderStateChangedError
        require_transition(stage.status, target)
        now = deps.clock.now()
        checkpoint: dict[str, Any] = {"completedAt": now.isoformat(), "keys": dict(result.keys), **result.data}
        finished = target is RenderStatus.COMPLETED
        following = None if finished else RenderStage(target.value)
        progress = 100 if finished else stage_base_progress(following) if following is not None else 0
        async with deps.transaction() as session:
            columns: dict[str, Any] = dict(result.columns)
            if result.commit is not None:
                columns.update(await result.commit(session))
            if finished:
                columns["completed_at"] = now
            row = await deps.store_factory(session).advance(
                run.render_id,
                Advance(
                    stage.status,
                    target,
                    following,
                    progress,
                    checkpoint={stage.value: checkpoint},
                    timings={stage.value: elapsed_ms},
                    columns=columns,
                ),
            )
            if row is None:
                raise RenderStateChangedError
        run.checkpoints[stage.value] = checkpoint
        run.progress.remember(progress)
        await run.progress.publish(target, following or RenderStage.FINALIZING, progress)
        return target

    async def _finish(self, run: RenderRun, target: RenderStatus, failure: RenderFailedError | None) -> None:
        deps = self._deps
        report = await self._failure_report(run, failure) if failure is not None else None
        async with deps.transaction() as session:
            row = await deps.store_factory(session).finish(
                run.render_id,
                Finish(
                    target=target,
                    at=deps.clock.now(),
                    error_code=failure.code.value if failure is not None else None,
                    error_message=failure.message if failure is not None else None,
                    timings=dict(run.timings),
                    validation_report=report_payload(report) if report is not None else None,
                ),
            )
        if row is None:
            return
        await run.progress.publish(
            target,
            stage_of(row),
            row.progress,
            error_code=row.error_code,
            error_message=row.error_message,
        )
        logger.info("media.render_finished", render_id=str(run.render_id), status=target.value, code=row.error_code)

    async def _failure_report(self, run: RenderRun, failure: RenderFailedError) -> ValidationReport | None:
        if failure.report is not None:
            return failure.report
        if not failure.issues:
            return None
        async with self._deps.transaction() as session:
            render = await self._deps.store_factory(session).get_unscoped(run.render_id)
        existing = report_from_payload(render.validation_report) if render and render.validation_report else None
        extra = ValidationReport(issues=failure.issues)
        return ValidationReport.merge(existing, extra) if existing is not None else extra
