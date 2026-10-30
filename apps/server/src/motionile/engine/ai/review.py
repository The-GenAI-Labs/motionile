from typing import Final

from motionile.engine.ai.llm.outputs import ReviewIssue, VisionReview
from motionile.engine.ai.ports import CompositionIssue

REVIEW_KIND: Final = "review"
REVIEW_CODE_PREFIX: Final = "review_"


def review_issue(issue: ReviewIssue) -> CompositionIssue:
    return CompositionIssue(
        code=f"{REVIEW_CODE_PREFIX}{issue.category.value}",
        severity="error" if issue.severity == "blocking" else "warning",
        kind=REVIEW_KIND,
        message=issue.description,
        scene_id=issue.scene_id,
        aspect=issue.aspect,
    )


def review_issues(review: VisionReview, *, scene_id: str | None = None) -> list[CompositionIssue]:
    return [review_issue(issue) for issue in review.issues if scene_id is None or issue.scene_id == scene_id]
