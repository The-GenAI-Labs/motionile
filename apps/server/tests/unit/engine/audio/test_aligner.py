from hypothesis import given
from hypothesis import strategies as st
from tests.unit.engine.audio.support import ScriptedTranscriber, StaticMeter

from motionile.engine.audio.models import WordTiming
from motionile.engine.audio.providers.aligner import Aligner, align_words, comparison_key
from motionile.engine.audio.timing import is_monotonic


def spoken(*items: tuple[str, int, int]) -> list[WordTiming]:
    return [WordTiming(*item) for item in items]


def test_exact_words_take_the_transcribed_timings() -> None:
    result = align_words(
        ["Hello,", "brave", "world."],
        spoken(("hello", 100, 400), ("brave", 450, 800), ("world", 850, 1300)),
        1500,
    )

    assert result == (WordTiming("Hello,", 100, 400), WordTiming("brave", 450, 800), WordTiming("world.", 850, 1300))


def test_case_and_punctuation_do_not_prevent_a_match() -> None:
    assert comparison_key("Don't!") == "dont"
    assert comparison_key("CAFÉ,") == comparison_key("café")


def test_numbers_missing_from_the_transcript_are_interpolated_between_neighbours() -> None:
    result = align_words(
        ["We", "sold", "42", "units", "today"],
        spoken(
            ("we", 0, 200),
            ("sold", 250, 600),
            ("forty", 650, 900),
            ("two", 900, 1100),
            ("units", 1150, 1500),
            ("today", 1550, 1900),
        ),
        2000,
    )

    assert [word.text for word in result] == ["We", "sold", "42", "units", "today"]
    assert result[2].start_ms == 650
    assert result[2].end_ms == 1100
    assert result[3] == WordTiming("units", 1150, 1500)


def test_unmatched_words_without_gap_words_split_the_silence_between_neighbours() -> None:
    result = align_words(
        ["alpha", "xx", "yyyy", "omega"],
        spoken(("alpha", 0, 500), ("omega", 1500, 2000)),
        2500,
    )

    assert result[0] == WordTiming("alpha", 0, 500)
    assert result[1].start_ms == 500
    assert result[3] == WordTiming("omega", 1500, 2000)
    assert result[1].end_ms == result[2].start_ms
    assert result[2].end_ms == 1500
    assert result[1].end_ms - result[1].start_ms < result[2].end_ms - result[2].start_ms


def test_leading_and_trailing_unmatched_words_use_the_audio_bounds() -> None:
    result = align_words(["intro", "middle", "outro"], spoken(("middle", 400, 800)), 1200)

    assert result[0].start_ms == 0
    assert result[0].end_ms == 400
    assert result[2].start_ms == 800
    assert result[2].end_ms == 1200


def test_an_empty_transcript_spreads_the_words_over_the_audio() -> None:
    result = align_words(["a", "bb", "ccc"], [], 600)

    assert result[0].start_ms == 0
    assert result[-1].end_ms == 600
    assert is_monotonic(result)


def test_near_miss_words_are_paired_instead_of_interpolated() -> None:
    result = align_words(["colour", "red"], spoken(("color", 100, 500), ("red", 550, 800)), 1000)

    assert result[0] == WordTiming("colour", 100, 500)


def test_no_source_words_means_no_timings() -> None:
    assert align_words([], spoken(("x", 0, 10)), 100) == ()


def test_timings_beyond_the_audio_are_clamped() -> None:
    result = align_words(["a", "b"], spoken(("a", 0, 500), ("b", 600, 5000)), 1000)

    assert result[1] == WordTiming("b", 600, 1000)


@given(
    st.lists(st.text(alphabet="abcdef0123", min_size=1, max_size=6), max_size=25),
    st.lists(
        st.tuples(st.text(alphabet="abcdef0123", min_size=1, max_size=6), st.integers(0, 9000), st.integers(0, 900)),
        max_size=25,
    ),
    st.integers(1, 10_000),
)
def test_always_one_monotonic_timing_per_source_word_inside_the_audio(
    source: list[str], heard: list[tuple[str, int, int]], duration: int
) -> None:
    result = align_words(source, [WordTiming(text, start, start + length) for text, start, length in heard], duration)

    assert [word.text for word in result] == source
    assert is_monotonic(result)
    assert all(0 <= word.start_ms <= word.end_ms <= duration for word in result)


async def test_aligner_transcribes_once_and_uses_the_given_duration() -> None:
    transcriber = ScriptedTranscriber(spoken(("hello", 0, 400), ("world", 450, 900)))
    meter = StaticMeter(5000)

    result = await Aligner(transcriber, meter).align(b"audio", "Hello world", "en", duration_ms=1000, filename="x.mp3")

    assert [word.text for word in result] == ["Hello", "world"]
    assert transcriber.calls == [("x.mp3", "en")]
    assert meter.calls == 0


async def test_aligner_measures_the_audio_when_no_duration_is_given() -> None:
    transcriber = ScriptedTranscriber([])
    meter = StaticMeter(1000)

    result = await Aligner(transcriber, meter).align(b"audio", "one two", None)

    assert meter.calls == 1
    assert result[-1].end_ms == 1000


async def test_aligner_skips_the_transcription_for_empty_text() -> None:
    transcriber = ScriptedTranscriber([])

    assert await Aligner(transcriber, StaticMeter(1)).align(b"audio", "   ", "en") == ()
    assert transcriber.calls == []
