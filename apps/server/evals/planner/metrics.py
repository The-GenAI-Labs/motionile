from collections.abc import Sequence

from evals.datasets import GoldenCase, scene_range_for
from evals.judge import ContentVerdict
from evals.matching import concept_covered, scene_token_sets
from evals.results import Measurement
from motionile.engine.ai.storyboard import Storyboard, StoryboardLimits, StoryboardScene

PERCENT: float = 100.0


def duration_compliant(storyboard: Storyboard, requested_ms: int, limits: StoryboardLimits) -> bool:
    allowed = requested_ms * limits.duration_tolerance_percent / PERCENT
    return abs(storyboard.scene_total_ms - requested_ms) <= allowed


def scene_rate(scene: StoryboardScene) -> float:
    return scene.word_count / (scene.target_duration_ms / 1000)


def speaking_rate_compliant(storyboard: Storyboard, limits: StoryboardLimits) -> bool:
    return all(
        limits.min_words_per_second <= scene_rate(scene) <= limits.max_words_per_second for scene in storyboard.scenes
    )


def scene_count_ok(storyboard: Storyboard, duration_seconds: int) -> bool:
    low, high = scene_range_for(duration_seconds)
    return low <= len(storyboard.scenes) <= high


def layout_notes_complete(storyboard: Storyboard) -> bool:
    return all(aspect in scene.layout_notes for scene in storyboard.scenes for aspect in storyboard.aspects)


def concept_coverage(case: GoldenCase, storyboard: Storyboard, confirmed: Sequence[str] | None) -> float:
    token_sets = scene_token_sets(storyboard)
    matched = [concept.name for concept in case.key_concepts if concept_covered(concept, token_sets)]
    if confirmed is not None:
        matched = [name for name in matched if name in set(confirmed)]
    return len(matched) / len(case.key_concepts)


def structure_scores(
    storyboard: Storyboard | None, requested_ms: int, duration_seconds: int, limits: StoryboardLimits
) -> dict[str, Measurement]:
    if storyboard is None:
        names = ("duration_compliance", "speaking_rate_compliance", "scene_count_ok", "layout_notes_complete")
        return {"plan_success_rate": Measurement(0.0)} | {name: Measurement(0.0) for name in names}
    return {
        "plan_success_rate": Measurement(1.0),
        "duration_compliance": Measurement(float(duration_compliant(storyboard, requested_ms, limits))),
        "speaking_rate_compliance": Measurement(float(speaking_rate_compliant(storyboard, limits))),
        "scene_count_ok": Measurement(float(scene_count_ok(storyboard, duration_seconds))),
        "layout_notes_complete": Measurement(float(layout_notes_complete(storyboard))),
    }


def judged_scores(verdict: ContentVerdict) -> dict[str, Measurement]:
    return {
        "factual_accuracy": Measurement(float(verdict.accuracy)),
        "pedagogy": Measurement(float(verdict.pedagogy)),
        "misconception_free": Measurement(float(not verdict.asserted_misconceptions)),
    }
