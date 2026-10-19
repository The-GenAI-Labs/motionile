from collections.abc import Iterable, Sequence

from motionile.engine.audio.models import WordTiming

MS_PER_SECOND = 1000


def seconds_to_ms(value: float) -> int:
    return round(value * MS_PER_SECOND)


def clamp_words(words: Iterable[WordTiming], duration_ms: int) -> tuple[WordTiming, ...]:
    ceiling = max(duration_ms, 0)
    clamped: list[WordTiming] = []
    previous_end = 0
    for word in words:
        start = min(max(word.start_ms, previous_end, 0), ceiling)
        end = min(max(word.end_ms, start), ceiling)
        clamped.append(WordTiming(word.text, start, end))
        previous_end = end
    return tuple(clamped)


def is_monotonic(words: Sequence[WordTiming]) -> bool:
    previous_end = 0
    for word in words:
        if word.start_ms < previous_end or word.end_ms < word.start_ms:
            return False
        previous_end = word.end_ms
    return True


def split_source_words(text: str) -> list[str]:
    return text.split()
