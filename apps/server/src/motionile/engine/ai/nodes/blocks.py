import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from motionile.engine.ai.graphs.deps import MS_PER_SECOND
from motionile.engine.ai.graphs.issues import issues_json
from motionile.engine.ai.job_options import AspectName
from motionile.engine.ai.ports import CompositionIssue, JobSnapshot
from motionile.engine.ai.prompts.delimit import delimit
from motionile.engine.ai.scenes.models import SceneModule
from motionile.engine.ai.storyboard import Storyboard, StoryboardIssue, StoryboardLimits, StoryboardScene
from motionile.engine.audio.narration_models import NarrationDocument, NarrationScene

AUDIENCE_LEVELS: Final = frozenset({"beginner", "intermediate", "advanced"})
SCENE_COUNT_BANDS: Final = ((20, (2, 3)), (40, (3, 5)), (75, (5, 8)))
LONGEST_SCENE_COUNT_RANGE: Final = (7, 12)
NONE_LABEL: Final = "none"


def pairs_text(pairs: Iterable[tuple[str, str]]) -> str:
    return "\n".join(f"{key}: {value}" for key, value in pairs)


def scene_count_range(duration_seconds: int, limits: StoryboardLimits) -> tuple[int, int]:
    low, high = LONGEST_SCENE_COUNT_RANGE
    for ceiling, band in SCENE_COUNT_BANDS:
        if duration_seconds <= ceiling:
            low, high = band
            break
    return max(low, limits.min_scenes), min(high, limits.max_scenes)


def audience_level(job: JobSnapshot) -> str | None:
    depth = job.preferences.depth
    return depth if depth in AUDIENCE_LEVELS else None


def text_limits(aspects: Sequence[AspectName], limits: StoryboardLimits) -> str:
    return ", ".join(f"{aspect}={limits.on_screen_text_chars[aspect]}" for aspect in aspects)


def plan_context(
    job: JobSnapshot,
    visual_skills: Sequence[str],
    extra: str,
    limits: StoryboardLimits,
    scenes_to_change: Sequence[str],
) -> str:
    options = job.options
    low, high = scene_count_range(options.duration_seconds, limits)
    pairs = [
        ("targetDurationSeconds", str(options.duration_seconds)),
        ("aspects", ", ".join(options.aspects)),
        ("language", options.language),
        ("styleSkill", options.style),
    ]
    level = audience_level(job)
    if level is not None:
        pairs.append(("audienceLevel", level))
    pairs.extend(
        [
            ("sceneCountRange", f"{low} to {high}"),
            ("wordsPerSecondRange", f"{limits.min_words_per_second:.1f} to {limits.max_words_per_second:.1f}"),
            ("onScreenTextLimits", text_limits(options.aspects, limits)),
            ("availableVisualSkills", ", ".join(visual_skills) or NONE_LABEL),
        ]
    )
    if scenes_to_change:
        pairs.append(("scenesToChange", ", ".join(scenes_to_change)))
    text = pairs_text(pairs)
    return delimit("context", f"{text}\n{extra}" if extra else text)


def query_block(job: JobSnapshot) -> str:
    return delimit("user_query", job.query or (job.topic.title if job.topic else ""))


def storyboard_block(storyboard: Storyboard) -> str:
    return delimit("previous_attempt", storyboard.model_dump_json(by_alias=True))


def instructions_block(instructions: str) -> str:
    return delimit("revision_instructions", instructions)


def issues_block(issues: Iterable[CompositionIssue]) -> str:
    return delimit("issues", issues_json(issues))


def storyboard_issues_block(issues: Sequence[StoryboardIssue]) -> str:
    entries = [
        {
            key: value
            for key, value in {
                "code": issue.code.value,
                "sceneId": issue.scene_id,
                "message": issue.message,
                "details": issue.detail or None,
            }.items()
            if value is not None
        }
        for issue in issues
    ]
    return delimit("issues", json.dumps(entries, ensure_ascii=False, separators=(",", ":")))


@dataclass(frozen=True, slots=True)
class SceneBrief:
    scene: StoryboardScene
    scene_count: int
    aspects: Sequence[AspectName]
    style: str
    language: str
    duration_ms: int


def indented(prefix: str, values: Iterable[str]) -> list[str]:
    return [f"  {prefix}{value}" for value in values]


def scene_context(brief: SceneBrief, attempt: int | None = None) -> str:
    scene = brief.scene
    lines = [
        f"sceneId: {scene.id}",
        f"position: {scene.position}",
        f"sceneCount: {brief.scene_count}",
        f"aspects: {', '.join(brief.aspects)}",
        f"style: {brief.style}",
        f"goal: {scene.goal}",
        f"visualBrief: {scene.visual_brief}",
        "layoutNotes:",
        *indented("", (f"{aspect}: {note}" for aspect, note in scene.layout_notes.items())),
        "onScreenText:",
        *indented("- ", scene.on_screen_text),
        f"keyTerms: {', '.join(scene.key_terms) or NONE_LABEL}",
        f"durationSeconds: {brief.duration_ms / MS_PER_SECOND:.2f}",
        f"language: {brief.language}",
    ]
    if attempt is not None:
        lines.append(f"attempt: {attempt}")
    return delimit("context", "\n".join(lines))


def review_context(brief: SceneBrief) -> str:
    scene = brief.scene
    lines = [
        f"sceneId: {scene.id}",
        f"style: {brief.style}",
        f"goal: {scene.goal}",
        "onScreenText:",
        *indented("- ", scene.on_screen_text),
        f"keyTerms: {', '.join(scene.key_terms) or NONE_LABEL}",
        f"aspects: {', '.join(brief.aspects)}",
    ]
    return delimit("context", "\n".join(lines))


def scene_brief(storyboard: Storyboard, narration: NarrationDocument, scene: StoryboardScene) -> SceneBrief:
    return SceneBrief(
        scene=scene,
        scene_count=len(storyboard.scenes),
        aspects=storyboard.aspects,
        style=storyboard.style_skill,
        language=storyboard.language,
        duration_ms=narration_scene_of(narration, scene.id).duration_ms,
    )


def narration_scene_of(narration: NarrationDocument, scene_id: str) -> NarrationScene:
    return next(scene for scene in narration.scenes if scene.id == scene_id)


def narration_block(scene: NarrationScene) -> str:
    words = [
        f"{word.index} {word.text} {word.scene_start_ms / MS_PER_SECOND:.2f} {word.scene_end_ms / MS_PER_SECOND:.2f}"
        for word in scene.words
    ]
    return delimit("narration", "\n".join([scene.text, "words (index text startSeconds endSeconds):", *words]))


def module_block(module: SceneModule) -> str:
    return delimit("previous_attempt", module.model_dump_json(by_alias=True, include={"builder", "css", "assets"}))


def module_text(module: SceneModule) -> str:
    return "\n".join([module.builder, module.css, *(asset.svg for asset in module.assets)])
