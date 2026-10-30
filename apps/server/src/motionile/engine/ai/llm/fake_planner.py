import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from motionile.engine.ai.job_options import AspectName
from motionile.engine.ai.storyboard import MAX_SCENES, MIN_SCENES, Storyboard, StoryboardLimits, StoryboardScene

SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
SECONDS_PER_SCENE = 14
RATE_MARGIN = 0.15
PLANNER_TOPICS: dict[str, tuple[str, ...]] = {
    "dns": ("dns", "domain name"),
    "binary-search": ("binary search",),
    "photosynthesis": ("photosynthesis",),
}


class FixtureTooSmallError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PlannerRequest:
    duration_ms: int
    aspects: Sequence[AspectName]
    language: str
    style: str | None


def planner_fixture_for(topic: str | None) -> str:
    if topic is None:
        return "default"
    normalized = topic.lower().replace("-", " ").replace("_", " ")
    for name, keywords in PLANNER_TOPICS.items():
        if any(keyword in normalized for keyword in keywords):
            return name
    return "default"


def split_sentences(narration: str) -> list[str]:
    return [sentence for sentence in SENTENCE_BOUNDARY.split(narration.strip()) if sentence]


def count_words(sentence: str) -> int:
    return len(sentence.split())


def scene_count_for(seconds: float, available: int) -> int:
    wanted = max(MIN_SCENES, math.ceil(seconds / SECONDS_PER_SCENE))
    return min(wanted, MAX_SCENES, available)


def spread_indexes(count: int, available: int) -> list[int]:
    return [int(position * (available - 1) / (count - 1) + 0.5) for position in range(count)]


def choose_sentences(pools: Sequence[list[str]], seconds: float, limits: StoryboardLimits) -> list[list[str]]:
    low = (limits.min_words_per_second + RATE_MARGIN) * seconds
    high = (limits.max_words_per_second - RATE_MARGIN) * seconds
    taken = [1] * len(pools)
    total = sum(count_words(pool[0]) for pool in pools)
    rank = 1
    while total < low and rank < max(len(pool) for pool in pools):
        for index, pool in enumerate(pools):
            if total >= low:
                break
            if taken[index] == rank and rank < len(pool) and total + count_words(pool[rank]) <= high:
                taken[index] += 1
                total += count_words(pool[rank])
        rank += 1
    if not low <= total <= high:
        raise FixtureTooSmallError(f"the fixture yields {total} words for {seconds:.0f} seconds")
    return [pool[:count] for pool, count in zip(pools, taken, strict=True)]


def split_durations(word_counts: Sequence[int], duration_ms: int) -> list[int]:
    total_words = sum(word_counts)
    durations = [round(words / total_words * duration_ms) for words in word_counts]
    durations[-1] = duration_ms - sum(durations[:-1])
    return durations


def scale_storyboard(source: Storyboard, request: PlannerRequest, limits: StoryboardLimits) -> Storyboard:
    seconds = request.duration_ms / 1000
    count = scene_count_for(seconds, len(source.scenes))
    chosen: list[StoryboardScene] = [source.scenes[index] for index in spread_indexes(count, len(source.scenes))]
    sentences = choose_sentences([split_sentences(scene.narration) for scene in chosen], seconds, limits)
    narrations = [" ".join(parts) for parts in sentences]
    durations = split_durations([count_words(text) for text in narrations], request.duration_ms)
    scenes = [
        StoryboardScene(
            id=scene.id,
            position=position,
            goal=scene.goal,
            narration=narration,
            visual_brief=scene.visual_brief,
            layout_notes={
                aspect: scene.layout_notes.get(aspect) or next(iter(scene.layout_notes.values()))
                for aspect in request.aspects
            },
            visual_skills=scene.visual_skills,
            key_terms=scene.key_terms,
            on_screen_text=scene.on_screen_text,
            target_duration_ms=duration,
        )
        for position, (scene, narration, duration) in enumerate(zip(chosen, narrations, durations, strict=True))
    ]
    return Storyboard(
        title=source.title,
        summary=source.summary,
        audience_level=source.audience_level,
        language=request.language,
        target_duration_ms=request.duration_ms,
        aspects=list(request.aspects),
        style_skill=request.style or source.style_skill,
        scenes=scenes,
    )
