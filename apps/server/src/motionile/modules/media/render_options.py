from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from motionile.core.schemas import StrictModel
from motionile.engine.render.models import Aspect as EngineAspect
from motionile.modules.media.domain import Aspect

MAX_SCENES = 60
MAX_SCENE_TEXT_CHARS = 2_000
MAX_TOTAL_TEXT_CHARS = 20_000
MIN_FPS = 24
MAX_FPS = 60
MAX_ASPECTS = 3
IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
PROVIDER_PATTERN = r"^[a-z][a-z0-9_]{1,39}$"

type SceneId = Annotated[str, StringConstraints(strip_whitespace=True, pattern=IDENTIFIER_PATTERN)]
type PartName = Annotated[str, StringConstraints(strip_whitespace=True, pattern=IDENTIFIER_PATTERN)]
type SceneText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_SCENE_TEXT_CHARS)]
type Fps = Annotated[int, Field(ge=MIN_FPS, le=MAX_FPS)]
type AspectList = Annotated[list[Aspect], Field(min_length=1, max_length=MAX_ASPECTS)]


def require_unique(values: list[str], label: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique")


class SceneScript(StrictModel):
    scene_id: SceneId
    text: SceneText


class UploadedScene(StrictModel):
    scene_id: SceneId
    audio_part: PartName
    text: SceneText | None = None


class ResolvedVoice(StrictModel):
    voice_id: UUID
    provider: Annotated[str, StringConstraints(strip_whitespace=True, pattern=PROVIDER_PATTERN)]
    provider_voice_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    language: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=35)]


class SynthesizeScenes(StrictModel):
    mode: Literal["synthesize"]
    scenes: Annotated[list[SceneScript], Field(min_length=1, max_length=MAX_SCENES)]

    @model_validator(mode="after")
    def check_scenes(self) -> "SynthesizeScenes":
        require_unique([scene.scene_id for scene in self.scenes], "scene IDs")
        if sum(len(scene.text) for scene in self.scenes) > MAX_TOTAL_TEXT_CHARS:
            raise ValueError(f"the narration may hold at most {MAX_TOTAL_TEXT_CHARS} characters in total")
        return self


class SynthesizeRequest(SynthesizeScenes):
    voice_id: UUID


class SynthesizeNarration(SynthesizeScenes):
    voice: ResolvedVoice


class UploadNarration(StrictModel):
    mode: Literal["upload"]
    scenes: Annotated[list[UploadedScene], Field(min_length=1, max_length=MAX_SCENES)]

    @model_validator(mode="after")
    def check_scenes(self) -> "UploadNarration":
        require_unique([scene.scene_id for scene in self.scenes], "scene IDs")
        require_unique([scene.audio_part for scene in self.scenes], "audio parts")
        total = sum(len(scene.text or "") for scene in self.scenes)
        if total > MAX_TOTAL_TEXT_CHARS:
            raise ValueError(f"the narration may hold at most {MAX_TOTAL_TEXT_CHARS} characters in total")
        return self


type NarrationRequest = Annotated[SynthesizeRequest | UploadNarration, Field(discriminator="mode")]
type StoredNarration = Annotated[SynthesizeNarration | UploadNarration, Field(discriminator="mode")]


class RenderChoices(StrictModel):
    aspects: AspectList
    music_track_id: UUID | None = None
    subtitles: bool = True
    burn_in_subtitles: bool = False

    @field_validator("aspects")
    @classmethod
    def unique_aspects(cls, value: list[Aspect]) -> list[Aspect]:
        require_unique([aspect.value for aspect in value], "aspects")
        return value

    @model_validator(mode="after")
    def burn_in_needs_subtitles(self) -> "RenderChoices":
        if self.burn_in_subtitles and not self.subtitles:
            raise ValueError("burnInSubtitles requires subtitles")
        return self


class RenderOptionsRequest(RenderChoices):
    fps: Fps | None = None
    narration: NarrationRequest


class RenderOptions(RenderChoices):
    fps: Fps
    narration: StoredNarration

    @property
    def scene_ids(self) -> list[str]:
        return [scene.scene_id for scene in self.narration.scenes]

    @property
    def engine_aspects(self) -> list[EngineAspect]:
        return [EngineAspect(aspect.value) for aspect in self.aspects]

    @property
    def is_synthesized(self) -> bool:
        return isinstance(self.narration, SynthesizeNarration)

    @property
    def uploaded_scenes(self) -> list[UploadedScene]:
        return list(self.narration.scenes) if isinstance(self.narration, UploadNarration) else []


def stored_options(request: RenderOptionsRequest, voice: ResolvedVoice | None, default_fps: int) -> RenderOptions:
    narration: SynthesizeNarration | UploadNarration
    if isinstance(request.narration, SynthesizeRequest):
        if voice is None:
            raise ValueError("a synthesized narration needs a resolved voice")
        narration = SynthesizeNarration(mode="synthesize", voice=voice, scenes=request.narration.scenes)
    else:
        narration = request.narration
    return RenderOptions(
        aspects=request.aspects,
        fps=request.fps if request.fps is not None else default_fps,
        narration=narration,
        music_track_id=request.music_track_id,
        subtitles=request.subtitles,
        burn_in_subtitles=request.burn_in_subtitles,
    )
