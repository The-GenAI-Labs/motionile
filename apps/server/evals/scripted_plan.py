import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from evals.datasets import GoldenCase, KeyConcept, scene_range_for
from evals.matching import content_tokens
from motionile.engine.ai.job_options import AspectName
from motionile.engine.ai.storyboard import Storyboard, StoryboardScene

SENTENCE_BOUNDARY: Final = re.compile(r"(?<=[.!?])\s+")
NOMINAL_RATE: Final = 2.4
UNDERSHOOT: Final = 0.96
OVERSHOOT: Final = 1.06
FILLER_ROUNDS: Final = 8
SHORT_FILLERS: Final[tuple[str, ...]] = ("Keep that in mind.", "Step by step.", "Here is why.", "It all connects.")
MAX_TERM_CHARS: Final = 36
MAX_KEY_TERM_CHARS: Final = 60
MAX_ON_SCREEN: Final = 2
FILLERS: Final[tuple[str, ...]] = (
    "Take a moment to picture how these parts fit together.",
    "Each step depends on the one before it, so the order matters.",
    "A small example makes the idea much easier to hold in your head.",
    "Keep this picture in mind, because the next scene builds on it.",
    "Notice how the pieces connect before we move on to the next idea.",
    "Seeing the whole flow once helps every detail fall into place.",
)


@dataclass(frozen=True, slots=True)
class PlanRequest:
    duration_ms: int
    aspects: Sequence[AspectName]
    language: str
    style: str


def words_in(sentence: str) -> int:
    return len(sentence.split())


def reference_sentences(case: GoldenCase) -> list[str]:
    return [sentence for sentence in SENTENCE_BOUNDARY.split(case.reference_notes.strip()) if sentence]


def overlap(concept: KeyConcept, sentence: str) -> float:
    sentence_tokens = set(content_tokens(sentence))
    best = 0.0
    for phrase in concept.phrases:
        wanted = content_tokens(phrase)
        if wanted:
            best = max(best, sum(1 for token in wanted if token in sentence_tokens) / len(wanted))
    return best


def ordered_sentences(case: GoldenCase) -> list[tuple[str, str | None]]:
    sentences = reference_sentences(case)
    chosen: list[tuple[str, str | None]] = []
    used: set[int] = set()
    intro = f"Let us walk through {case.subcategory.replace('-', ' ')} one step at a time."
    chosen.append((intro, None))
    for concept in case.key_concepts:
        scores = [(overlap(concept, sentence), -index) for index, sentence in enumerate(sentences)]
        best_score, negative_index = max(scores)
        index = -negative_index
        if best_score > 0 and index not in used:
            used.add(index)
            chosen.append((sentences[index], concept.name))
    chosen.extend((sentence, None) for index, sentence in enumerate(sentences) if index not in used)
    chosen.extend((f"A key idea here is {concept.name}.", concept.name) for concept in case.key_concepts)
    return chosen


def select(pool: Sequence[tuple[str, str | None]], target_words: int) -> list[tuple[str, str | None]]:
    selected: list[tuple[str, str | None]] = []
    total = 0
    lower = target_words * UNDERSHOOT
    upper = target_words * OVERSHOOT
    for index in range(len(pool) + len(FILLERS) * FILLER_ROUNDS):
        if total >= lower:
            break
        sentence, concept = pool[index] if index < len(pool) else (FILLERS[(index - len(pool)) % len(FILLERS)], None)
        if total + words_in(sentence) > upper and selected:
            continue
        selected.append((sentence, concept))
        total += words_in(sentence)
    for index in range(len(SHORT_FILLERS) * FILLER_ROUNDS):
        if total >= lower:
            break
        sentence = SHORT_FILLERS[index % len(SHORT_FILLERS)]
        if total + words_in(sentence) <= upper:
            selected.append((sentence, None))
            total += words_in(sentence)
    return selected


def partition(sentences: Sequence[tuple[str, str | None]], scene_count: int) -> list[list[tuple[str, str | None]]]:
    count = max(2, min(scene_count, len(sentences)))
    total = sum(words_in(sentence) for sentence, _ in sentences)
    groups: list[list[tuple[str, str | None]]] = [[] for _ in range(count)]
    running = 0
    for position, entry in enumerate(sentences):
        remaining_sentences = len(sentences) - position
        scene = min(count - 1, int(running / total * count))
        occupied = sum(1 for group in groups if group)
        if remaining_sentences <= count - occupied:
            scene = next(index for index, group in enumerate(groups) if not group)
        groups[scene].append(entry)
        running += words_in(entry[0])
    return [group for group in groups if group]


def split_durations(word_counts: Sequence[int], duration_ms: int) -> list[int]:
    total = sum(word_counts)
    durations = [round(words / total * duration_ms) for words in word_counts]
    durations[-1] = duration_ms - sum(durations[:-1])
    return durations


def scene_from(
    position: int, group: Sequence[tuple[str, str | None]], duration_ms: int, request: PlanRequest, topic: str
) -> StoryboardScene:
    narration = " ".join(sentence for sentence, _ in group)
    concepts = list(dict.fromkeys(concept for _, concept in group if concept is not None))
    terms = [concept[:MAX_KEY_TERM_CHARS] for concept in concepts]
    on_screen = [concept[:MAX_TERM_CHARS] for concept in concepts[:MAX_ON_SCREEN]]
    focus = concepts[0] if concepts else topic
    return StoryboardScene(
        id=f"scene-{position + 1}",
        position=position,
        goal=f"Explain {focus}"[:300],
        narration=narration,
        visual_brief=f"Show {focus} as a simple labelled diagram that builds up as it is spoken.",
        layout_notes=dict.fromkeys(
            request.aspects, "Keep the main diagram centered and every label inside the safe area."
        ),
        visual_skills=[],
        key_terms=terms,
        on_screen_text=on_screen,
        target_duration_ms=duration_ms,
    )


def build_storyboard(
    pool: Sequence[tuple[str, str | None]], request: PlanRequest, *, title: str, summary: str, topic: str
) -> Storyboard:
    seconds = request.duration_ms / 1000
    low, high = scene_range_for(round(seconds))
    groups = partition(select(pool, round(seconds * NOMINAL_RATE)), (low + high) // 2)
    durations = split_durations(
        [sum(words_in(sentence) for sentence, _ in group) for group in groups], request.duration_ms
    )
    scenes = [
        scene_from(position, group, duration, request, topic)
        for position, (group, duration) in enumerate(zip(groups, durations, strict=True))
    ]
    return Storyboard(
        title=title[:120],
        summary=summary[:600],
        audience_level="beginner",
        language=request.language,
        target_duration_ms=request.duration_ms,
        aspects=list(request.aspects),
        style_skill=request.style,
        scenes=scenes,
    )


def scripted_storyboard(case: GoldenCase, request: PlanRequest) -> Storyboard:
    return build_storyboard(
        ordered_sentences(case),
        request,
        title=case.query,
        summary=reference_sentences(case)[0],
        topic=case.subcategory.replace("-", " "),
    )


def generic_storyboard(query: str, request: PlanRequest) -> Storyboard:
    question = query.strip().rstrip("?.! ")
    pool = [
        (f"Let us answer this question: {question}.", None),
        ("We will build the answer one small step at a time.", None),
    ]
    return build_storyboard(
        pool, request, title=query, summary=f"A short explainer that answers: {question}.", topic=question
    )
