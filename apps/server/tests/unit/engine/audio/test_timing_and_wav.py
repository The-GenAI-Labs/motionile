import struct

import pytest
from hypothesis import given
from hypothesis import strategies as st

from motionile.engine.audio.models import WordTiming
from motionile.engine.audio.timing import clamp_words, is_monotonic, seconds_to_ms, split_source_words
from motionile.engine.audio.wav import WavError, build_wav, finalize_streamed_wav, parse_wav


def test_seconds_round_to_nearest_millisecond() -> None:
    assert seconds_to_ms(0.0004) == 0
    assert seconds_to_ms(0.0005) == 0
    assert seconds_to_ms(1.2346) == 1235
    assert seconds_to_ms(2.0) == 2000


def test_clamp_words_limits_to_duration_and_removes_overlap() -> None:
    words = [WordTiming("a", 0, 500), WordTiming("b", 400, 900), WordTiming("c", 880, 2000)]

    clamped = clamp_words(words, 1000)

    assert clamped == (WordTiming("a", 0, 500), WordTiming("b", 500, 900), WordTiming("c", 900, 1000))


def test_clamp_words_pushes_words_after_the_end_to_the_end() -> None:
    clamped = clamp_words([WordTiming("a", 0, 100), WordTiming("b", 5000, 6000)], 1000)

    assert clamped[1] == WordTiming("b", 1000, 1000)


def test_clamp_words_repairs_inverted_and_negative_timings() -> None:
    clamped = clamp_words([WordTiming("a", -50, -10), WordTiming("b", 300, 100)], 1000)

    assert clamped == (WordTiming("a", 0, 0), WordTiming("b", 300, 300))


@given(
    st.lists(
        st.tuples(st.integers(-1000, 20000), st.integers(-1000, 20000)),
        max_size=40,
    ),
    st.integers(0, 15000),
)
def test_clamp_words_always_returns_monotonic_words_inside_the_duration(
    spans: list[tuple[int, int]], duration: int
) -> None:
    words = [WordTiming(f"w{index}", start, end) for index, (start, end) in enumerate(spans)]

    clamped = clamp_words(words, duration)

    assert len(clamped) == len(words)
    assert is_monotonic(clamped)
    assert all(0 <= word.start_ms <= word.end_ms <= duration for word in clamped)
    assert [word.text for word in clamped] == [word.text for word in words]


def test_is_monotonic_detects_overlap() -> None:
    assert is_monotonic([WordTiming("a", 0, 10), WordTiming("b", 10, 20)])
    assert not is_monotonic([WordTiming("a", 0, 10), WordTiming("b", 9, 20)])
    assert not is_monotonic([WordTiming("a", 10, 5)])


def test_split_source_words_uses_unicode_whitespace() -> None:
    text = "  one" + chr(9) + "two" + chr(0xA0) + "three" + chr(10)
    assert split_source_words(text) == ["one", "two", "three"]


def test_wav_round_trips_header_fields_and_embedded_text() -> None:
    pcm = struct.pack("<4h", 1, -1, 2, -2)

    data = build_wav(pcm, sample_rate=16000, embedded_text="héllo world")
    info = parse_wav(data)

    assert (info.sample_rate, info.channels, info.frames) == (16000, 1, 4)
    assert info.embedded_text == "héllo world"
    assert data[info.data_offset : info.data_offset + info.data_bytes] == pcm


def test_wav_duration_is_derived_from_frames() -> None:
    data = build_wav(bytes(2 * 8000), sample_rate=16000)

    assert parse_wav(data).duration_ms == 500


@pytest.mark.parametrize("payload", [b"", b"RIFF", b"RIFF\x00\x00\x00\x00AVI LIST", b"x" * 64])
def test_parse_wav_rejects_garbage(payload: bytes) -> None:
    with pytest.raises(WavError):
        parse_wav(payload)


def test_finalize_streamed_wav_patches_unknown_sizes() -> None:
    data = bytearray(build_wav(bytes(2000), sample_rate=8000))
    info = parse_wav(bytes(data))
    data[4:8] = struct.pack("<I", 0xFFFFFFFF)
    data[info.data_offset - 4 : info.data_offset] = struct.pack("<I", 0xFFFFFFFF)

    fixed = finalize_streamed_wav(bytes(data))

    assert struct.unpack("<I", fixed[4:8])[0] == len(fixed) - 8
    assert struct.unpack("<I", fixed[info.data_offset - 4 : info.data_offset])[0] == 2000
    assert parse_wav(fixed).frames == 1000
