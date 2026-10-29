import re
import unicodedata
from collections.abc import Iterable, Sequence
from typing import Final

from evals.datasets import KeyConcept
from motionile.engine.ai.storyboard import Storyboard, StoryboardScene

WORD: Final = re.compile(r"[^\W_]+", re.UNICODE)
MATCH_RATIO: Final = 0.8
SUFFIXES: Final = ("ing", "ed", "es", "s")
MIN_STEM: Final = 3
STOP_WORDS: Final = frozenset(
    [
        *("a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in", "is", "it", "its", "of"),
        *("on", "or", "that", "the", "this", "to", "was", "what", "when", "where", "which", "why", "with"),
    ]
)


def stem(word: str) -> str:
    for suffix in SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= MIN_STEM:
            word = word[: -len(suffix)]
            break
    if word.endswith("e") and len(word) > MIN_STEM:
        return word[:-1]
    return word


def content_tokens(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", text).casefold()
    return [stem(word) for word in WORD.findall(folded) if word not in STOP_WORDS]


def phrase_matches(phrase: str, text_tokens: set[str], ratio: float = MATCH_RATIO) -> bool:
    wanted = content_tokens(phrase)
    if not wanted:
        return False
    present = sum(1 for token in wanted if token in text_tokens)
    return present / len(wanted) >= ratio


def scene_text(scene: StoryboardScene) -> str:
    return " ".join([scene.narration, *scene.on_screen_text, *scene.key_terms])


def scene_token_sets(storyboard: Storyboard) -> list[set[str]]:
    return [set(content_tokens(scene_text(scene))) for scene in storyboard.scenes]


def concept_covered(concept: KeyConcept, token_sets: Sequence[set[str]]) -> bool:
    return any(phrase_matches(phrase, tokens) for tokens in token_sets for phrase in concept.phrases)


def covered_concepts(concepts: Iterable[KeyConcept], storyboard: Storyboard) -> list[str]:
    token_sets = scene_token_sets(storyboard)
    return [concept.name for concept in concepts if concept_covered(concept, token_sets)]


def narration_text(storyboard: Storyboard) -> str:
    return "\n".join(scene.narration for scene in storyboard.scenes)


def storyboard_strings(storyboard: Storyboard) -> list[str]:
    strings = [storyboard.title, storyboard.summary]
    for scene in storyboard.scenes:
        strings.extend(
            [
                scene.goal,
                scene.narration,
                scene.visual_brief,
                *scene.layout_notes.values(),
                *scene.on_screen_text,
                *scene.key_terms,
            ]
        )
    return strings
