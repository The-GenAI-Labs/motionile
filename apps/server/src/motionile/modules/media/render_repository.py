from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import bindparam, func, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.ids import new_id
from motionile.modules.media.domain import (
    TERMINAL_RENDER_STATUSES,
    RenderStage,
    RenderStatus,
    RenditionStatus,
)
from motionile.modules.media.models import Render, Rendition

FRESH_ROWS = {"populate_existing": True}
TERMINAL_VALUES = tuple(status.value for status in TERMINAL_RENDER_STATUSES)
ACTIVE_STAGE_VALUES = tuple(stage.status.value for stage in RenderStage)
ACTIVE_VALUES = (RenderStatus.QUEUED.value, *ACTIVE_STAGE_VALUES)


@dataclass(frozen=True, slots=True)
class NewRender:
    id: UUID
    owner_user_id: UUID
    source: str
    options: Mapping[str, Any]
    composition_asset_id: UUID
    checkpoints: Mapping[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class Advance:
    expected: RenderStatus
    target: RenderStatus
    stage: RenderStage | None
    progress: int
    checkpoint: Mapping[str, Any] = field(default_factory=dict[str, Any])
    timings: Mapping[str, int] = field(default_factory=dict[str, int])
    columns: Mapping[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class Finish:
    target: RenderStatus
    at: datetime
    error_code: str | None = None
    error_message: str | None = None
    timings: Mapping[str, int] = field(default_factory=dict[str, int])
    validation_report: Mapping[str, Any] | None = None
    stalled_before: datetime | None = None


@dataclass(frozen=True, slots=True)
class NewRendition:
    render_id: UUID
    aspect: str
    width: int
    height: int
    asset_id: UUID
    poster_webp_asset_id: UUID | None
    poster_jpeg_asset_id: UUID | None
    duration_ms: int
    burned_in_subtitles: bool


@dataclass(frozen=True, slots=True)
class CancelOutcome:
    render: Render
    cancelled_now: bool


class RenderJobStore(Protocol):
    async def insert(self, row: NewRender) -> Render: ...

    async def get_unscoped(self, render_id: UUID) -> Render | None: ...

    async def advance(self, render_id: UUID, change: Advance) -> Render | None: ...

    async def finish(self, render_id: UUID, finish: Finish) -> Render | None: ...

    async def touch(
        self, render_id: UUID, *, progress: int | None = None, stage: RenderStage | None = None
    ) -> bool: ...

    async def request_cancel(self, owner_user_id: UUID, render_id: UUID, now: datetime) -> CancelOutcome | None: ...

    async def set_validation_report(self, render_id: UUID, report: Mapping[str, Any]) -> None: ...

    async def stalled(self, before: datetime, limit: int) -> list[UUID]: ...

    async def add_rendition(self, row: NewRendition) -> Rendition: ...


def merged_json(column: Any, patch: Mapping[str, Any]) -> Any:
    return column.op("||")(bindparam(None, dict(patch), type_=JSONB))


class SqlRenderJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def insert(self, row: NewRender) -> Render:
        render = Render(
            id=row.id,
            owner_user_id=row.owner_user_id,
            source=row.source,
            status=RenderStatus.QUEUED.value,
            stage=None,
            progress=0,
            options=dict(row.options),
            composition_asset_id=row.composition_asset_id,
            stage_timings={},
            checkpoints=dict(row.checkpoints),
        )
        self.session.add(render)
        await self.session.flush()
        await self.session.refresh(render)
        return render

    async def get_unscoped(self, render_id: UUID) -> Render | None:
        statement = select(Render).where(Render.id == render_id).execution_options(**FRESH_ROWS)
        return await self.session.scalar(statement)

    async def advance(self, render_id: UUID, change: Advance) -> Render | None:
        values: dict[str, Any] = {
            "status": change.target.value,
            "progress": change.progress,
            "updated_at": func.now(),
            "checkpoints": merged_json(Render.checkpoints, change.checkpoint),
            "stage_timings": merged_json(Render.stage_timings, change.timings),
            **change.columns,
        }
        if change.stage is not None:
            values["stage"] = change.stage.value
        statement = (
            update(Render)
            .where(Render.id == render_id, Render.status == change.expected.value)
            .values(**values)
            .returning(Render)
            .execution_options(**FRESH_ROWS)
        )
        return await self.session.scalar(statement)

    async def finish(self, render_id: UUID, finish: Finish) -> Render | None:
        values: dict[str, Any] = {
            "status": finish.target.value,
            "completed_at": finish.at,
            "error_code": finish.error_code,
            "error_message": finish.error_message,
            "updated_at": func.now(),
            "stage_timings": merged_json(Render.stage_timings, finish.timings),
        }
        if finish.validation_report is not None:
            values["validation_report"] = dict(finish.validation_report)
        conditions = [Render.id == render_id, Render.status.not_in(TERMINAL_VALUES)]
        if finish.stalled_before is not None:
            conditions.append(Render.updated_at < finish.stalled_before)
        statement = update(Render).where(*conditions).values(**values).returning(Render).execution_options(**FRESH_ROWS)
        return await self.session.scalar(statement)

    async def touch(self, render_id: UUID, *, progress: int | None = None, stage: RenderStage | None = None) -> bool:
        values: dict[str, Any] = {"updated_at": func.now()}
        if progress is not None:
            values["progress"] = func.greatest(Render.progress, progress)
        if stage is not None:
            values["stage"] = stage.value
        statement = (
            update(Render)
            .where(Render.id == render_id, Render.status.in_(ACTIVE_STAGE_VALUES))
            .values(**values)
            .returning(Render.id)
        )
        return await self.session.scalar(statement) is not None

    async def request_cancel(self, owner_user_id: UUID, render_id: UUID, now: datetime) -> CancelOutcome | None:
        selection = (
            select(Render)
            .where(Render.id == render_id, Render.owner_user_id == owner_user_id)
            .with_for_update()
            .execution_options(**FRESH_ROWS)
        )
        render = await self.session.scalar(selection)
        if render is None:
            return None
        if render.status in TERMINAL_VALUES:
            return CancelOutcome(render, cancelled_now=False)
        if render.status == RenderStatus.QUEUED.value:
            cancelled = await self.session.scalar(
                update(Render)
                .where(Render.id == render_id, Render.status == RenderStatus.QUEUED.value)
                .values(
                    status=RenderStatus.CANCELLED.value,
                    cancel_requested_at=now,
                    completed_at=now,
                    updated_at=func.now(),
                )
                .returning(Render)
                .execution_options(**FRESH_ROWS)
            )
            if cancelled is not None:
                return CancelOutcome(cancelled, cancelled_now=True)
        requested = await self.session.scalar(
            update(Render)
            .where(Render.id == render_id, Render.status.not_in(TERMINAL_VALUES))
            .values(cancel_requested_at=func.coalesce(Render.cancel_requested_at, now), updated_at=func.now())
            .returning(Render)
            .execution_options(**FRESH_ROWS)
        )
        return CancelOutcome(requested or render, cancelled_now=False)

    async def set_validation_report(self, render_id: UUID, report: Mapping[str, Any]) -> None:
        await self.session.execute(
            update(Render).where(Render.id == render_id).values(validation_report=dict(report), updated_at=func.now())
        )

    async def stalled(self, before: datetime, limit: int) -> list[UUID]:
        statement = (
            select(Render.id)
            .where(Render.status.in_(ACTIVE_VALUES), Render.updated_at < before)
            .order_by(Render.updated_at, Render.id)
            .limit(limit)
        )
        return list(await self.session.scalars(statement))

    async def add_rendition(self, row: NewRendition) -> Rendition:
        rendition = Rendition(
            id=new_id(),
            render_id=row.render_id,
            aspect=row.aspect,
            width=row.width,
            height=row.height,
            asset_id=row.asset_id,
            poster_webp_asset_id=row.poster_webp_asset_id,
            poster_jpeg_asset_id=row.poster_jpeg_asset_id,
            status=RenditionStatus.READY.value,
            duration_ms=row.duration_ms,
            burned_in_subtitles=row.burned_in_subtitles,
        )
        self.session.add(rendition)
        await self.session.flush()
        return rendition
