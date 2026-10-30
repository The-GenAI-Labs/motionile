from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from motionile.engine.ai.base import AiModel
from motionile.engine.ai.job_options import (
    LANGUAGE_PATTERN,
    MAX_DURATION_SECONDS,
    MIN_DURATION_SECONDS,
    AspectName,
    LanguageCode,
    SceneIdentifier,
    Slug,
)

STORYBOARD_VERSION: Literal[1] = 1
MIN_SCENES = 2
MAX_SCENES = 12
MIN_SCENE_MS = 1_000
MAX_SCENE_MS = 120_000
MAX_NARRATION_CHARS = 2_000
MAX_VISUAL_BRIEF_CHARS = 4_000
MAX_ON_SCREEN_ITEMS = 6
MAX_ON_SCREEN_ITEM_CHARS = 120
MAX_KEY_TERMS = 8
MAX_VISUAL_SKILLS = 3

type AudienceLevel = Literal["beginner", "intermediate", "advanced"]
type Line = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
type Narration = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_NARRATION_CHARS)]
type VisualBrief = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_VISUAL_BRIEF_CHARS)
]
type LayoutNote = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
type KeyTerm = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
type OnScreenText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_ON_SCREEN_ITEM_CHARS)
]


class StoryboardScene(AiModel):
    id: SceneIdentifier
    position: Annotated[int, Field(ge=0, lt=MAX_SCENES)]
    goal: Line
    narration: Narration
    visual_brief: VisualBrief
    layout_notes: Annotated[dict[AspectName, LayoutNote], Field(min_length=1)]
    visual_skills: Annotated[list[Slug], Field(max_length=MAX_VISUAL_SKILLS)] = Field(default_factory=list)
    key_terms: Annotated[list[KeyTerm], Field(max_length=MAX_KEY_TERMS)] = Field(default_factory=list)
    on_screen_text: Annotated[list[OnScreenText], Field(max_length=MAX_ON_SCREEN_ITEMS)] = Field(default_factory=list)
    target_duration_ms: Annotated[int, Field(ge=MIN_SCENE_MS, le=MAX_SCENE_MS)]

    @property
    def word_count(self) -> int:
        return len(self.narration.split())


class Storyboard(AiModel):
    version: Literal[1] = STORYBOARD_VERSION
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
    audience_level: AudienceLevel
    language: Annotated[str, StringConstraints(strip_whitespace=True, pattern=LANGUAGE_PATTERN)]
    target_duration_ms: Annotated[int, Field(ge=MIN_DURATION_SECONDS * 1000, le=MAX_DURATION_SECONDS * 1000)]
    aspects: Annotated[list[AspectName], Field(min_length=1, max_length=3)]
    style_skill: Slug
    scenes: Annotated[list[StoryboardScene], Field(min_length=MIN_SCENES, max_length=MAX_SCENES)]

    @field_validator("aspects")
    @classmethod
    def aspects_are_unique(cls, value: list[AspectName]) -> list[AspectName]:
        if len(set(value)) != len(value):
            raise ValueError("aspects must be unique")
        return value

    @model_validator(mode="after")
    def scenes_are_ordered_and_unique(self) -> "Storyboard":
        identifiers = [scene.id for scene in self.scenes]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("scene IDs must be unique")
        if [scene.position for scene in self.scenes] != list(range(len(self.scenes))):
            raise ValueError("scene positions must be 0..n-1 in order")
        return self

    @property
    def scene_total_ms(self) -> int:
        return sum(scene.target_duration_ms for scene in self.scenes)


class StoryboardIssueCode(StrEnum):
    SCENE_COUNT = "scene_count"
    TOTAL_DURATION = "total_duration"
    SPEAKING_RATE_LOW = "speaking_rate_low"
    SPEAKING_RATE_HIGH = "speaking_rate_high"
    ON_SCREEN_TEXT_LENGTH = "on_screen_text_length"
    ASPECTS_MISMATCH = "aspects_mismatch"
    LAYOUT_NOTES_MISSING = "layout_notes_missing"
    LANGUAGE_MISMATCH = "language_mismatch"
    STYLE_MISMATCH = "style_mismatch"


class StoryboardIssue(AiModel):
    code: StoryboardIssueCode
    scene_id: str | None = None
    message: str
    detail: dict[str, int | float | str] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StoryboardLimits:
    min_scenes: int = MIN_SCENES
    max_scenes: int = MAX_SCENES
    duration_tolerance_percent: int = 10
    min_words_per_second: float = 2.0
    max_words_per_second: float = 2.8
    on_screen_text_chars: Mapping[AspectName, int] = field(
        default_factory=lambda: {"16:9": 160, "9:16": 90, "1:1": 120}
    )

    @property
    def nominal_words_per_second(self) -> float:
        return (self.min_words_per_second + self.max_words_per_second) / 2

    def spoken_duration_ms(self, narration: str) -> int:
        return round(len(narration.split()) / self.nominal_words_per_second * 1000)


@dataclass(frozen=True, slots=True)
class StoryboardExpectation:
    duration_ms: int
    aspects: Sequence[AspectName]
    language: LanguageCode
    style: Slug


def validate_storyboard(
    storyboard: Storyboard, expectation: StoryboardExpectation, limits: StoryboardLimits
) -> list[StoryboardIssue]:
    issues: list[StoryboardIssue] = []
    issues.extend(count_issues(storyboard, limits))
    issues.extend(header_issues(storyboard, expectation))
    issues.extend(duration_issues(storyboard, expectation, limits))
    for scene in storyboard.scenes:
        issues.extend(scene_issues(scene, expectation, limits))
    return issues


def count_issues(storyboard: Storyboard, limits: StoryboardLimits) -> list[StoryboardIssue]:
    count = len(storyboard.scenes)
    if limits.min_scenes <= count <= limits.max_scenes:
        return []
    return [
        StoryboardIssue(
            code=StoryboardIssueCode.SCENE_COUNT,
            message=f"The storyboard has {count} scenes; it needs {limits.min_scenes} to {limits.max_scenes}",
            detail={"scenes": count, "minimum": limits.min_scenes, "maximum": limits.max_scenes},
        )
    ]


def header_issues(storyboard: Storyboard, expectation: StoryboardExpectation) -> list[StoryboardIssue]:
    issues: list[StoryboardIssue] = []
    if set(storyboard.aspects) != set(expectation.aspects):
        issues.append(
            StoryboardIssue(
                code=StoryboardIssueCode.ASPECTS_MISMATCH,
                message=(
                    f"The storyboard lists aspects {sorted(storyboard.aspects)}; "
                    f"the job asks for {sorted(expectation.aspects)}"
                ),
            )
        )
    if storyboard.language != expectation.language:
        issues.append(
            StoryboardIssue(
                code=StoryboardIssueCode.LANGUAGE_MISMATCH,
                message=f"The storyboard language is {storyboard.language}; the job asks for {expectation.language}",
            )
        )
    if storyboard.style_skill != expectation.style:
        issues.append(
            StoryboardIssue(
                code=StoryboardIssueCode.STYLE_MISMATCH,
                message=f"The storyboard style is {storyboard.style_skill}; the job asks for {expectation.style}",
            )
        )
    return issues


def duration_issues(
    storyboard: Storyboard, expectation: StoryboardExpectation, limits: StoryboardLimits
) -> list[StoryboardIssue]:
    total = storyboard.scene_total_ms
    allowed = expectation.duration_ms * limits.duration_tolerance_percent / 100
    if abs(total - expectation.duration_ms) <= allowed:
        return []
    return [
        StoryboardIssue(
            code=StoryboardIssueCode.TOTAL_DURATION,
            message=(
                f"The scene durations add up to {total / 1000:.1f} s; the job asks for "
                f"{expectation.duration_ms / 1000:.1f} s within {limits.duration_tolerance_percent} percent"
            ),
            detail={"totalMs": total, "requestedMs": expectation.duration_ms},
        )
    ]


def scene_issues(
    scene: StoryboardScene, expectation: StoryboardExpectation, limits: StoryboardLimits
) -> list[StoryboardIssue]:
    issues = rate_issues(scene, limits)
    missing = [aspect for aspect in expectation.aspects if aspect not in scene.layout_notes]
    if missing:
        issues.append(
            StoryboardIssue(
                code=StoryboardIssueCode.LAYOUT_NOTES_MISSING,
                scene_id=scene.id,
                message=f"Scene {scene.id} has no layout notes for {missing}",
            )
        )
    issues.extend(on_screen_issues(scene, expectation, limits))
    return issues


def rate_issues(scene: StoryboardScene, limits: StoryboardLimits) -> list[StoryboardIssue]:
    rate = scene.word_count / (scene.target_duration_ms / 1000)
    if rate < limits.min_words_per_second:
        code = StoryboardIssueCode.SPEAKING_RATE_LOW
    elif rate > limits.max_words_per_second:
        code = StoryboardIssueCode.SPEAKING_RATE_HIGH
    else:
        return []
    return [
        StoryboardIssue(
            code=code,
            scene_id=scene.id,
            message=(
                f"Scene {scene.id} has {scene.word_count} words in {scene.target_duration_ms / 1000:.1f} s "
                f"({rate:.2f} words per second); the allowed range is "
                f"{limits.min_words_per_second:.1f} to {limits.max_words_per_second:.1f}"
            ),
            detail={"words": scene.word_count, "targetMs": scene.target_duration_ms, "rate": round(rate, 3)},
        )
    ]


def on_screen_issues(
    scene: StoryboardScene, expectation: StoryboardExpectation, limits: StoryboardLimits
) -> list[StoryboardIssue]:
    total = sum(len(item) for item in scene.on_screen_text)
    issues: list[StoryboardIssue] = []
    for aspect in expectation.aspects:
        allowed = limits.on_screen_text_chars.get(aspect)
        if allowed is not None and total > allowed:
            issues.append(
                StoryboardIssue(
                    code=StoryboardIssueCode.ON_SCREEN_TEXT_LENGTH,
                    scene_id=scene.id,
                    message=f"Scene {scene.id} has {total} characters of on-screen text; {aspect} allows {allowed}",
                    detail={"characters": total, "allowed": allowed, "aspect": aspect},
                )
            )
    return issues
