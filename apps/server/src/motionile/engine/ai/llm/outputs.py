from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from motionile.engine.ai.base import AiModel
from motionile.engine.ai.job_options import AspectName, SceneIdentifier, Slug

MAX_ISSUES = 24
MAX_FRAMES = 36
MAX_SELECTED_SKILLS = 3

type IssueMessage = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
type Score = Annotated[int, Field(ge=1, le=5)]


class CritiqueCategory(StrEnum):
    PEDAGOGY = "pedagogy"
    ACCURACY = "accuracy"
    PACING = "pacing"


class CritiqueIssue(AiModel):
    scene_id: SceneIdentifier
    category: CritiqueCategory
    message: IssueMessage
    suggested_fix: IssueMessage


class StoryboardCritique(AiModel):
    verdict: Literal["pass", "revise"]
    blocking_issues: Annotated[list[CritiqueIssue], Field(max_length=MAX_ISSUES)] = Field(
        default_factory=list[CritiqueIssue]
    )

    @property
    def is_clean(self) -> bool:
        return self.verdict == "pass" and not self.blocking_issues


class ReviewCategory(StrEnum):
    LEGIBILITY = "legibility"
    LAYOUT = "layout"
    RELEVANCE = "relevance"
    STYLE = "style"
    VISUAL_ERROR = "visual_error"


class FrameScores(AiModel):
    scene_id: SceneIdentifier
    aspect: AspectName
    legibility: Score
    layout: Score
    relevance: Score
    style_consistency: Score
    visual_errors: Score


class ReviewIssue(AiModel):
    scene_id: SceneIdentifier
    aspect: AspectName
    category: ReviewCategory
    severity: Literal["blocking", "minor"]
    description: IssueMessage


class VisionReview(AiModel):
    frames: Annotated[list[FrameScores], Field(max_length=MAX_FRAMES)] = Field(default_factory=list[FrameScores])
    issues: Annotated[list[ReviewIssue], Field(max_length=MAX_ISSUES)] = Field(default_factory=list[ReviewIssue])

    @property
    def blocking_issues(self) -> list[ReviewIssue]:
        return [issue for issue in self.issues if issue.severity == "blocking"]


class SkillChoice(AiModel):
    slug: Slug
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class SkillSelection(AiModel):
    style: SkillChoice
    visual: Annotated[list[SkillChoice], Field(max_length=MAX_SELECTED_SKILLS)] = Field(
        default_factory=list[SkillChoice]
    )
    domain: Annotated[list[SkillChoice], Field(max_length=2)] = Field(default_factory=list[SkillChoice])
