import hashlib
from collections.abc import Sequence

import pytest
from hypothesis import given
from hypothesis import strategies as st

from motionile.engine.audio.voice_clone import (
    CONSENT_PHRASE,
    CONSENT_WORDS,
    consent_similarity,
    evaluate_consent,
    generate_consent_sentence,
    normalize_for_comparison,
)


class SeededRandom:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.counter = 0

    def next_int(self) -> int:
        self.counter += 1
        digest = hashlib.sha256(f"{self.seed}:{self.counter}".encode()).digest()
        return int.from_bytes(digest[:8], "big")

    def randrange(self, stop: int, /) -> int:
        return self.next_int() % stop

    def sample(self, population: Sequence[str], k: int) -> list[str]:
        pool = list(population)
        return [pool.pop(self.randrange(len(pool))) for _ in range(k)]


SENTENCE = (
    "I confirm that this is my own voice and I agree that Motionile may create a synthetic copy of it. "
    "My words are river, silver, candle and planet, and my number is 4 7 2 9."
)


def test_normalization_lowercases_folds_and_strips_punctuation() -> None:
    assert normalize_for_comparison("  Hello,   WORLD!!  ") == "hello world"
    assert normalize_for_comparison("Café déjà-vu") == "cafe deja vu"
    assert normalize_for_comparison("don't “stop”") == "dont stop"
    assert normalize_for_comparison("".join(chr(0xFF21 + offset) for offset in range(3))) == "abc"


def test_digits_are_spelled_so_numerals_and_words_compare_equal() -> None:
    assert normalize_for_comparison("4 7 2 9") == "four seven two nine"
    assert normalize_for_comparison("4729") == "four seven two nine"
    assert normalize_for_comparison("four seven two nine") == "four seven two nine"


def test_devanagari_text_keeps_its_vowel_signs() -> None:
    text = "नमस्ते दुनिया!"

    assert normalize_for_comparison(text) == text.removesuffix("!")


def test_identical_text_scores_one() -> None:
    assert consent_similarity(SENTENCE, SENTENCE) == 1.0


def test_numerals_and_case_differences_still_score_one() -> None:
    transcript = SENTENCE.lower().replace("4 7 2 9", "four seven two nine").replace(",", "")

    assert consent_similarity(SENTENCE, transcript) == 1.0


def test_small_recognition_errors_stay_above_the_threshold() -> None:
    noisy = SENTENCE.replace("Motionile", "motion isle").replace("planet", "plannet").replace("silver", "sylver")

    verdict = evaluate_consent(SENTENCE, noisy)

    assert verdict.matched
    assert 0.85 <= verdict.similarity < 1.0


def test_one_missing_word_stays_above_the_threshold() -> None:
    dropped = SENTENCE.replace("synthetic ", "")

    assert evaluate_consent(SENTENCE, dropped).matched


def test_a_different_sentence_is_rejected() -> None:
    other = "Please remember to buy milk and bread on the way home tonight before the shops close"

    verdict = evaluate_consent(SENTENCE, other)

    assert not verdict.matched
    assert verdict.similarity < 0.3


def test_the_wrong_digits_and_words_are_rejected() -> None:
    wrong = SENTENCE.replace("river, silver, candle and planet", "anchor, hammer, window and tiger").replace(
        "4 7 2 9", "1 3 5 8"
    )

    assert not evaluate_consent(SENTENCE, wrong, threshold=0.9).matched


def test_replaying_an_old_recording_does_not_match_a_new_sentence() -> None:
    first = generate_consent_sentence(SeededRandom(1))
    second = generate_consent_sentence(SeededRandom(2))

    assert first != second
    assert evaluate_consent(second, first, threshold=0.95).similarity < 0.95


def test_empty_transcripts_score_zero() -> None:
    assert consent_similarity(SENTENCE, "") == 0.0
    assert consent_similarity(SENTENCE, "...") == 0.0
    assert consent_similarity("", SENTENCE) == 0.0


def test_threshold_is_applied_by_the_caller() -> None:
    similarity = consent_similarity(SENTENCE, SENTENCE.replace("river", "rover"))

    assert evaluate_consent(SENTENCE, SENTENCE.replace("river", "rover"), threshold=0.999).matched is False
    assert evaluate_consent(SENTENCE, SENTENCE.replace("river", "rover"), threshold=0.5).matched is True
    assert evaluate_consent(SENTENCE, SENTENCE, threshold=0.85).similarity > similarity


@given(st.text(max_size=120), st.text(max_size=120))
def test_similarity_is_within_bounds(expected: str, transcript: str) -> None:
    assert 0.0 <= consent_similarity(expected, transcript) <= 1.0


def test_generated_sentence_has_the_fixed_phrase_words_and_digits() -> None:
    sentence = generate_consent_sentence(SeededRandom(7))

    assert sentence.startswith(CONSENT_PHRASE)
    words_part = sentence.split("My words are ")[1].split(", and my number is ")[0]
    chosen = words_part.replace(" and ", ", ").split(", ")
    assert len(set(chosen)) == len(chosen) == 4
    assert all(word in CONSENT_WORDS for word in chosen)
    digits = sentence.rsplit("my number is ", maxsplit=1)[1].rstrip(".").split(" ")
    assert len(digits) == 4
    assert all(digit.isdigit() and len(digit) == 1 for digit in digits)


def test_generated_sentence_is_deterministic_for_a_seeded_rng() -> None:
    assert generate_consent_sentence(SeededRandom(5)) == generate_consent_sentence(SeededRandom(5))


@given(st.integers(0, 2**32))
def test_generated_sentence_is_short_and_pronounceable(seed: int) -> None:
    sentence = generate_consent_sentence(SeededRandom(seed))

    assert len(sentence) <= 300
    assert sentence.isascii()
    assert evaluate_consent(sentence, sentence).matched


def test_default_generation_uses_system_randomness() -> None:
    assert len({generate_consent_sentence() for _ in range(5)}) > 1


def test_every_curated_word_is_plain_lowercase_letters() -> None:
    assert len(set(CONSENT_WORDS)) == len(CONSENT_WORDS)
    assert all(word.isalpha() and word.islower() and 3 <= len(word) <= 9 for word in CONSENT_WORDS)


@pytest.mark.parametrize("threshold", [0.0, 1.0])
def test_threshold_boundaries(threshold: float) -> None:
    verdict = evaluate_consent(SENTENCE, SENTENCE, threshold=threshold)

    assert verdict.matched
