from uuid import UUID

from motionile.modules.media.domain import RenderSource, RenderStage, RenderStatus
from motionile.modules.media.models import Render
from motionile.modules.media.schemas import RenderView

MUSIC_TRACK_OPTION = "musicTrackId"


def render_view(render: Render) -> RenderView:
    return RenderView(
        id=render.id,
        source=RenderSource(render.source),
        status=RenderStatus(render.status),
        stage=RenderStage(render.stage) if render.stage is not None else None,
        progress=render.progress,
        options=dict(render.options),
        duration_ms=render.duration_ms,
        validation_report=dict(render.validation_report) if render.validation_report is not None else None,
        stage_timings=dict(render.stage_timings),
        error_code=render.error_code,
        error_message=render.error_message,
        cancel_requested_at=render.cancel_requested_at,
        started_at=render.started_at,
        completed_at=render.completed_at,
        created_at=render.created_at,
        updated_at=render.updated_at,
    )


def music_track_id(render: Render) -> UUID | None:
    value = render.options.get(MUSIC_TRACK_OPTION)
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None
