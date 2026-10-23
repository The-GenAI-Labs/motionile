import itertools
import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from motionile.engine.audio.models import WordTiming
from motionile.engine.audio.subtitles import (
    CAPTION_LAYOUTS,
    Aspect,
    Cue,
    CueSettings,
    ass_timestamp,
    build_cues,
    format_timestamp,
    layout_lines,
    parse_aspect,
    render_ass,
    render_srt,
    render_webvtt,
)

DANDA = chr(0x964)
TOKENS = [
    "the",
    "quick",
    "brown",
    "fox,",
    "jumps",
    "over",
    "lazy",
    "dogs.",
    "Wait!",
    "really?",
    "so;",
    "and:",
    "extraordinarily",
    "internationalization",
    f"namaste{DANDA}",
    "a",
    "I",
    "x" * 41,
    "y" * 60,
    "https://example.com/" + "z" * 50,
]


def timed(text: str, start: int, duration: int = 300) -> WordTiming:
    return WordTiming(text, start, start + duration)


def sentence(text: str, start: int = 0, duration: int = 300, gap: int = 50) -> list[WordTiming]:
    words: list[WordTiming] = []
    cursor = start
    for token in text.split():
        words.append(timed(token, cursor, duration))
        cursor += duration + gap
    return words


@st.composite
def spoken_words(draw: st.DrawFn) -> list[WordTiming]:
    cursor = draw(st.integers(0, 3000))
    words: list[WordTiming] = []
    for _ in range(draw(st.integers(1, 80))):
        text = draw(st.sampled_from(TOKENS))
        duration = draw(st.integers(60, 1500))
        words.append(WordTiming(text, cursor, cursor + duration))
        cursor += duration + draw(st.integers(0, 900))
    return words


@given(spoken_words())
def test_cues_are_ordered_and_never_overlap(words: list[WordTiming]) -> None:
    cues = build_cues(words)

    for cue in cues:
        assert cue.start_ms < cue.end_ms
    for earlier, later in itertools.pairwise(cues):
        assert earlier.end_ms <= later.start_ms
        assert earlier.start_ms < later.start_ms


@given(spoken_words())
def test_cues_respect_line_character_and_duration_limits(words: list[WordTiming]) -> None:
    for cue in build_cues(words):
        assert 1 <= len(cue.lines) <= 2
        assert all(0 < len(line) <= 42 for line in cue.lines)
        assert cue.end_ms - cue.start_ms <= 6000


@given(spoken_words())
def test_every_word_is_covered_exactly_once(words: list[WordTiming]) -> None:
    cues = build_cues(words)

    covered = [index for cue in cues for index in range(cue.first_word, cue.end_word)]
    assert covered == list(range(len(words)))


@given(spoken_words())
def test_cue_times_follow_the_word_timings(words: list[WordTiming]) -> None:
    cues = build_cues(words)

    for position, cue in enumerate(cues):
        first, last = words[cue.first_word], words[cue.end_word - 1]
        next_start = cues[position + 1].start_ms if position + 1 < len(cues) else None
        assert cue.start_ms == first.start_ms
        assert cue.end_ms >= min(last.end_ms, cue.start_ms + 6000)
        assert cue.end_ms <= max(last.end_ms + 120, cue.start_ms + 1000)
        minimum = 1000 if next_start is None else min(1000, next_start - cue.start_ms)
        assert cue.end_ms - cue.start_ms >= minimum


@given(spoken_words())
def test_cue_text_is_the_words_in_order(words: list[WordTiming]) -> None:
    for cue in build_cues(words):
        expected = [word.text for word in words[cue.first_word : cue.end_word]]
        if all(len(token) <= 42 for token in expected):
            assert " ".join(cue.lines).split() == expected


def test_sentence_punctuation_always_breaks() -> None:
    words = sentence("Hello there. How are you? Fine! Thanks")

    cues = build_cues(words)

    assert [cue.text for cue in cues] == ["Hello there.", "How are you?", "Fine!", "Thanks"]


def test_devanagari_danda_breaks_a_sentence() -> None:
    words = sentence(f"नमस्ते दोस्तों{DANDA} आप कैसे हैं")

    assert len(build_cues(words)) == 2


def test_closing_quotes_after_sentence_punctuation_still_break() -> None:
    words = sentence('He said "stop." Then left')

    assert [cue.first_word for cue in build_cues(words)] == [0, 3]


def test_clause_punctuation_breaks_once_the_cue_has_enough_text() -> None:
    words = sentence("However, we kept going until the end, then stopped")

    cues = build_cues(words)

    assert [cue.text.replace("\n", " ") for cue in cues] == ["However, we kept going until the end,", "then stopped"]


def test_clause_punctuation_in_a_short_cue_does_not_break() -> None:
    cues = build_cues(sentence("Yes, we can"))

    assert len(cues) == 1


def test_a_pause_of_350_ms_breaks_but_349_does_not() -> None:
    long_pause = [timed("one", 0), timed("two", 300 + 350), timed("three", 1000)]
    short_pause = [timed("one", 0), timed("two", 300 + 349), timed("three", 1000)]

    assert [cue.first_word for cue in build_cues(long_pause)] == [0, 1]
    assert [cue.first_word for cue in build_cues(short_pause)] == [0]


def test_forced_breaks_split_cues() -> None:
    words = sentence("one two three four")

    cues = build_cues(words, forced_breaks={2})

    assert [(cue.first_word, cue.end_word) for cue in cues] == [(0, 2), (2, 4)]


def test_cue_never_exceeds_two_lines_of_42_characters() -> None:
    words = sentence("alpha " * 30)

    cues = build_cues(words)

    assert len(cues) > 1
    assert all(len(line) <= 42 and len(cue.lines) <= 2 for cue in cues for line in cue.lines)


def test_a_cue_never_exceeds_six_seconds() -> None:
    words = [timed("w", index * 1000, 900) for index in range(20)]

    cues = build_cues(words)

    assert all(cue.end_ms - cue.start_ms <= 6000 for cue in cues)
    assert len(cues) >= 4


def test_short_cues_are_extended_into_the_gap_but_never_past_the_next_cue() -> None:
    words = [timed("Hi.", 0, 200), timed("There", 5000, 300), timed("again.", 5400, 300)]

    cues = build_cues(words)

    assert (cues[0].start_ms, cues[0].end_ms) == (0, 1000)
    assert cues[1].start_ms == 5000


def test_extension_stops_at_the_next_cue_start() -> None:
    words = [timed("Hi.", 0, 200), timed("Next", 600, 200)]

    cues = build_cues(words)

    assert cues[0].end_ms == 600


def test_cue_ends_120_ms_after_the_last_word() -> None:
    cues = build_cues([timed("long", 0, 2000)])

    assert cues[0].end_ms == 2120


def test_end_is_trimmed_to_the_next_cue() -> None:
    words = [timed("one.", 0, 2000), timed("two", 2050, 500)]

    assert build_cues(words)[0].end_ms == 2050


def test_lines_are_balanced() -> None:
    lines = layout_lines(["the", "quick", "brown", "fox", "jumps", "over", "the", "lazy", "dog", "again"], 42)

    assert lines == ("the quick brown fox jumps", "over the lazy dog again")
    assert layout_lines(["short", "line"], 42) == ("short line",)
    two = layout_lines(["aaaa", "bbbb", "cccc", "dddd", "eeee", "ffff", "gggg", "hhhh", "iiii", "jjjj"], 29)
    assert two is not None
    assert abs(len(two[0]) - len(two[1])) <= 5


def test_a_single_overlong_token_is_hard_split_and_truncated() -> None:
    assert layout_lines(["y" * 60], 42) == ("y" * 42, "y" * 18)
    truncated = layout_lines(["z" * 200], 42)
    assert truncated is not None
    assert len(truncated) == 2
    assert truncated[1].endswith(chr(0x2026))


def test_no_words_means_no_cues() -> None:
    assert build_cues([]) == ()
    assert build_cues([WordTiming(" ", 0, 10)]) == ()


def test_custom_settings_are_honoured() -> None:
    words = sentence("one two three four five six")

    cues = build_cues(words, settings=CueSettings(max_line_chars=10))

    assert all(len(line) <= 10 for cue in cues for line in cue.lines)


def test_timestamp_formats() -> None:
    assert format_timestamp(3_723_456, ".") == "01:02:03.456"
    assert format_timestamp(59, ",") == "00:00:00,059"
    assert ass_timestamp(3_723_456, round_up=False) == "1:02:03.45"
    assert ass_timestamp(3_723_456, round_up=True) == "1:02:03.46"


def cues_for_formats() -> tuple[Cue, ...]:
    return build_cues(
        [
            timed("Tom", 0, 300),
            timed("&", 350, 200),
            timed("<Jerry>.", 600, 400),
            timed("Second", 3000, 400),
            timed("line", 3450, 400),
        ]
    )


def test_webvtt_output() -> None:
    document = render_webvtt(cues_for_formats())

    assert document == (
        "WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.120\nTom &amp; &lt;Jerry&gt;.\n\n"
        "2\n00:00:03.000 --> 00:00:04.000\nSecond line\n"
    )


def test_srt_output() -> None:
    document = render_srt(cues_for_formats())

    assert document == (
        "1\n00:00:00,000 --> 00:00:01,120\nTom & <Jerry>.\n\n2\n00:00:03,000 --> 00:00:04,000\nSecond line\n"
    )


def test_two_line_cue_renders_both_lines() -> None:
    cues = build_cues(sentence("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"))

    assert "\n" in render_srt(cues).split("\n\n")[0].split("\n", 2)[2]


@pytest.mark.parametrize(
    ("aspect", "resolution", "band"),
    [("16:9", (1920, 1080), 160), ("9:16", (1080, 1920), 420), ("1:1", (1080, 1080), 200)],
)
def test_ass_uses_the_aspect_resolution_and_stays_inside_the_caption_band(
    aspect: Aspect, resolution: tuple[int, int], band: int
) -> None:
    document = render_ass(cues_for_formats(), aspect)
    layout = CAPTION_LAYOUTS[aspect]

    assert f"PlayResX: {resolution[0]}" in document
    assert f"PlayResY: {resolution[1]}" in document
    assert layout.band_px == band
    assert layout.margin_v + layout.block_height <= band
    style = next(line for line in document.splitlines() if line.startswith("Style: Default"))
    fields = style.removeprefix("Style: ").split(",")
    assert fields[1] == "Geist"
    assert fields[3] == "&H00FFFFFF"
    assert fields[5] == fields[6] == "&H66000000"
    assert fields[15] == "3"
    assert int(fields[21]) == layout.margin_v
    assert int(fields[18]) == 2
    assert int(fields[19]) == layout.margin_h


def test_ass_dialogue_lines() -> None:
    document = render_ass(cues_for_formats(), "16:9")

    dialogues = [line for line in document.splitlines() if line.startswith("Dialogue:")]
    assert dialogues[0] == "Dialogue: 0,0:00:00.00,0:00:01.12,Default,,0,0,0,,Tom & <Jerry>."
    assert dialogues[1].startswith("Dialogue: 0,0:00:03.00,0:00:04.00,Default")


def test_ass_uses_the_devanagari_font_for_hindi_and_escapes_override_braces() -> None:
    hindi = build_cues(sentence("नमस्ते दुनिया"))
    braces = build_cues(sentence("{bold}"))

    document = render_ass(hindi, "9:16")
    escaped = render_ass(braces, "9:16")

    assert "Style: Devanagari,Noto Sans Devanagari," in document
    assert re.search(r"^Dialogue: .*,Devanagari,,0,0,0,,", document, re.MULTILINE)
    assert "{" not in escaped.split("[Events]")[1].split("Text\n")[1]


def test_ass_two_lines_use_the_ass_line_break() -> None:
    cues = build_cues(sentence("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"))

    assert "\\N" in render_ass(cues, "16:9")


def test_aspect_labels() -> None:
    assert parse_aspect("16x9") == "16:9"
    assert parse_aspect("9:16") == "9:16"
    with pytest.raises(ValueError, match="unsupported aspect"):
        parse_aspect("4:3")
