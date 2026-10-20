from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from motionile.core.schemas import ResponseModel
from motionile.modules.media.domain import Aspect
from motionile.modules.media.render_options import Fps, RenderChoices
from motionile.modules.media.schemas import MusicTrackView, RenderView, RenditionView

GOLDEN_NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"

type GoldenName = Annotated[str, StringConstraints(pattern=GOLDEN_NAME_PATTERN)]


def all_aspects() -> list[Aspect]:
    return [Aspect.LANDSCAPE, Aspect.PORTRAIT, Aspect.SQUARE]


class GoldenRenderRequest(RenderChoices):
    aspects: Annotated[list[Aspect], Field(min_length=1, max_length=3)] = Field(default_factory=all_aspects)
    voice_id: UUID
    fps: Fps | None = None


class GoldenSceneView(ResponseModel):
    scene_id: str
    text: str


class GoldenCompositionView(ResponseModel):
    name: str
    title: str
    description: str
    language: str
    scene_ids: list[str]
    scenes: list[GoldenSceneView]


class GoldenCatalogView(ResponseModel):
    items: list[GoldenCompositionView]


class RenderBedView(RenderView):
    renditions: list[RenditionView]


class BedMusicTrackView(ResponseModel):
    id: UUID
    title: str
    mood: str
    bpm: int | None = None
    duration_ms: int
    attribution: str | None = None


class BedMusicTrackList(ResponseModel):
    items: list[BedMusicTrackView]


def bed_track(track: MusicTrackView) -> BedMusicTrackView:
    return BedMusicTrackView(
        id=track.id,
        title=track.title,
        mood=track.mood,
        bpm=track.bpm,
        duration_ms=track.duration_ms,
        attribution=track.attribution_text,
    )
