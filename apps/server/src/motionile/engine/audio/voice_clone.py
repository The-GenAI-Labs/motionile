import re
import secrets
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Protocol

CONSENT_PHRASE = "I confirm that this is my own voice and I agree that Motionile may create a synthetic copy of it."
CONSENT_WORD_COUNT = 4
CONSENT_DIGIT_COUNT = 4
MAX_CONSENT_CHARACTERS = 300
DEFAULT_MATCH_THRESHOLD = 0.85
MAX_COMPARED_WORDS = 400
NEAR_MATCH_RATIO = 0.7
CONSENT_WORDS = (
    "amber",
    "anchor",
    "apple",
    "badger",
    "basket",
    "bridge",
    "butter",
    "candle",
    "canyon",
    "carpet",
    "castle",
    "cherry",
    "circle",
    "cotton",
    "dolphin",
    "dragon",
    "engine",
    "falcon",
    "feather",
    "forest",
    "garden",
    "ginger",
    "glacier",
    "guitar",
    "hammer",
    "harbor",
    "island",
    "jacket",
    "jungle",
    "kettle",
    "ladder",
    "lantern",
    "lemon",
    "magnet",
    "marble",
    "meadow",
    "mirror",
    "needle",
    "orange",
    "paddle",
    "pepper",
    "pillow",
    "planet",
    "pocket",
    "rabbit",
    "ribbon",
    "river",
    "rocket",
    "saddle",
    "silver",
    "spider",
    "summer",
    "sunset",
    "teapot",
    "thunder",
    "tiger",
    "tunnel",
    "valley",
    "velvet",
    "violin",
    "walnut",
    "willow",
    "window",
    "winter",
)
DIGIT_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
APOSTROPHES = frozenset(chr(codepoint) for codepoint in (0x27, 0x2019, 0x2BC, 0x60))
COMBINING_PREFIX = "COMBINING"
WHITESPACE = re.compile(r"\s+")


class ConsentRandom(Protocol):
    def sample(self, population: Sequence[str], k: int) -> list[str]: ...

    def randrange(self, stop: int, /) -> int: ...


@dataclass(frozen=True, slots=True)
class ConsentVerdict:
    similarity: float
    threshold: float
    matched: bool


def digit_to_word(character: str) -> str:
    return DIGIT_WORDS[unicodedata.digit(character)]


def normalize_for_comparison(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text).casefold()
    pieces: list[str] = []
    for character in decomposed:
        category = unicodedata.category(character)
        if character in APOSTROPHES:
            continue
        if category == "Mn" and unicodedata.name(character, "").startswith(COMBINING_PREFIX):
            continue
        if category == "Nd":
            pieces.append(f" {digit_to_word(character)} ")
        elif category[0] in {"P", "S", "Z", "C"}:
            pieces.append(" ")
        else:
            pieces.append(character)
    return WHITESPACE.sub(" ", unicodedata.normalize("NFC", "".join(pieces))).strip()


def substitution_cost(left: str, right: str) -> float:
    if left == right:
        return 0.0
    ratio = SequenceMatcher(None, left, right).ratio()
    return 1.0 - ratio if ratio >= NEAR_MATCH_RATIO else 1.0


def word_distance(expected: Sequence[str], spoken: Sequence[str]) -> float:
    previous = [float(index) for index in range(len(spoken) + 1)]
    for row, expected_word in enumerate(expected, start=1):
        current = [float(row)]
        for column, spoken_word in enumerate(spoken, start=1):
            current.append(
                min(
                    previous[column] + 1.0,
                    current[column - 1] + 1.0,
                    previous[column - 1] + substitution_cost(expected_word, spoken_word),
                )
            )
        previous = current
    return previous[-1]


def consent_similarity(expected: str, transcript: str) -> float:
    expected_words = normalize_for_comparison(expected).split()
    spoken_words = normalize_for_comparison(transcript).split()[:MAX_COMPARED_WORDS]
    if not expected_words or not spoken_words:
        return 0.0
    distance = word_distance(expected_words, spoken_words)
    return max(0.0, 1.0 - distance / max(len(expected_words), len(spoken_words)))


def evaluate_consent(expected: str, transcript: str, threshold: float = DEFAULT_MATCH_THRESHOLD) -> ConsentVerdict:
    similarity = consent_similarity(expected, transcript)
    return ConsentVerdict(similarity=similarity, threshold=threshold, matched=similarity >= threshold)


def generate_consent_sentence(rng: ConsentRandom | None = None) -> str:
    source = rng if rng is not None else secrets.SystemRandom()
    words = source.sample(CONSENT_WORDS, CONSENT_WORD_COUNT)
    digits = " ".join(str(source.randrange(10)) for _ in range(CONSENT_DIGIT_COUNT))
    sentence = f"{CONSENT_PHRASE} My words are {', '.join(words)}, and my number is {digits}."
    if len(sentence) > MAX_CONSENT_CHARACTERS:
        raise ValueError("the consent sentence is too long")
    return sentence
