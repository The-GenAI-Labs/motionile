import unicodedata
from collections.abc import Sequence
from difflib import SequenceMatcher

from motionile.engine.audio.models import WordTiming
from motionile.engine.audio.providers.base import AudioDurationMeter, Transcriber
from motionile.engine.audio.timing import clamp_words, split_source_words

FUZZY_PAIR_RATIO = 0.6
KEPT_CATEGORIES = frozenset({"L", "M", "N"})


def comparison_key(word: str) -> str:
    folded = unicodedata.normalize("NFKC", word).casefold()
    return "".join(character for character in folded if unicodedata.category(character)[0] in KEPT_CATEGORIES)


def match_words(source_keys: Sequence[str], spoken_keys: Sequence[str]) -> dict[int, int]:
    matcher = SequenceMatcher(None, list(source_keys), list(spoken_keys), autojunk=False)
    matches: dict[int, int] = {}
    for tag, source_start, source_end, spoken_start, spoken_end in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(source_end - source_start):
                matches[source_start + offset] = spoken_start + offset
        elif tag == "replace" and source_end - source_start == spoken_end - spoken_start:
            for offset in range(source_end - source_start):
                left = source_keys[source_start + offset]
                right = spoken_keys[spoken_start + offset]
                if left and right and SequenceMatcher(None, left, right).ratio() >= FUZZY_PAIR_RATIO:
                    matches[source_start + offset] = spoken_start + offset
    return matches


def spread(words: Sequence[str], keys: Sequence[str], lower: int, upper: int) -> list[WordTiming]:
    weights = [max(len(key), 1) for key in keys]
    total = sum(weights)
    span = max(upper - lower, 0)
    timings: list[WordTiming] = []
    consumed = 0
    for word, weight in zip(words, weights, strict=True):
        start = lower + round(span * consumed / total)
        consumed += weight
        end = lower + round(span * consumed / total)
        timings.append(WordTiming(word, start, end))
    return timings


def gap_bounds(spoken: Sequence[WordTiming], previous: int, following: int, duration_ms: int) -> tuple[int, int]:
    between = spoken[previous + 1 : following]
    if between:
        return between[0].start_ms, between[-1].end_ms
    lower = spoken[previous].end_ms if previous >= 0 else 0
    upper = spoken[following].start_ms if following < len(spoken) else duration_ms
    return lower, max(upper, lower)


def align_words(source: Sequence[str], spoken: Sequence[WordTiming], duration_ms: int) -> tuple[WordTiming, ...]:
    if not source:
        return ()
    source_keys = [comparison_key(word) for word in source]
    spoken_keys = [comparison_key(word.text) for word in spoken]
    matches = match_words(source_keys, spoken_keys)
    timings: list[WordTiming | None] = [None] * len(source)
    for source_index, spoken_index in matches.items():
        timings[source_index] = WordTiming(
            source[source_index], spoken[spoken_index].start_ms, spoken[spoken_index].end_ms
        )
    index = 0
    while index < len(source):
        if timings[index] is not None:
            index += 1
            continue
        run_end = index
        while run_end < len(source) and timings[run_end] is None:
            run_end += 1
        previous = matches[index - 1] if index > 0 else -1
        following = matches[run_end] if run_end < len(source) else len(spoken)
        lower, upper = gap_bounds(spoken, previous, following, duration_ms)
        filled = spread(source[index:run_end], source_keys[index:run_end], lower, upper)
        timings[index:run_end] = filled
        index = run_end
    return clamp_words([timing for timing in timings if timing is not None], duration_ms)


class Aligner:
    def __init__(self, transcriber: Transcriber, meter: AudioDurationMeter) -> None:
        self._transcriber = transcriber
        self._meter = meter

    async def align(
        self,
        audio: bytes,
        text: str,
        language: str | None,
        *,
        filename: str = "speech.mp3",
        duration_ms: int | None = None,
    ) -> tuple[WordTiming, ...]:
        source = split_source_words(text)
        if not source:
            return ()
        duration = duration_ms if duration_ms is not None else await self._meter.measure_ms(audio)
        transcript = await self._transcriber.transcribe(audio, filename, language)
        return align_words(source, transcript.words, duration)
