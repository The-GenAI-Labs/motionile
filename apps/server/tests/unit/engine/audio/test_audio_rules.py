import pytest

from motionile.engine.audio.audio_validation import (
    AudioRejectedError,
    AudioUploadLimits,
    Container,
    check_probe,
    decode_check_arguments,
    detect_container,
    wav_arguments,
)
from motionile.engine.audio.sources import needs_seekable_input
from motionile.engine.ffmpeg import MediaProbe, StreamInfo, StreamKind

LIMITS = AudioUploadLimits(max_bytes=1_000_000, min_duration_ms=1000, max_duration_ms=300_000)


def stream(kind: StreamKind, index: int = 0, duration_ms: int | None = 5000) -> StreamInfo:
    return StreamInfo(
        index=index,
        kind=kind,
        codec_name="x",
        profile=None,
        sample_rate=44100,
        channels=2,
        width=None,
        height=None,
        pix_fmt=None,
        color_space=None,
        color_primaries=None,
        color_transfer=None,
        color_range=None,
        frame_count=None,
        frame_rate=None,
        duration_ms=duration_ms,
        bit_rate=None,
    )


def probe(format_name: str, *streams: StreamInfo, duration_ms: int | None = 5000) -> MediaProbe:
    return MediaProbe(format_name=format_name, duration_ms=duration_ms, size_bytes=None, streams=tuple(streams))


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"RIFF\x00\x00\x00\x00WAVEfmt ", "wav"),
        (b"ID3\x04\x00\x00\x00\x00\x00\x00", "mp3"),
        (b"\xff\xfb\x90\x00" + b"\x00" * 8, "mp3"),
        (b"\xff\xf1\x50\x80" + b"\x00" * 8, "aac"),
        (b"OggS\x00\x02" + b"\x00" * 8, "ogg"),
        (b"fLaC\x00\x00\x00\x22", "flac"),
        (b"\x00\x00\x00\x20ftypM4A \x00\x00", "mp4"),
        (b"\x1a\x45\xdf\xa3\x01\x00\x00\x00", "matroska"),
    ],
)
def test_known_containers_are_recognised_by_their_leading_bytes(data: bytes, expected: str) -> None:
    assert detect_container(data) == expected


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"hello world, this is text",
        b"PK\x03\x04" + b"\x00" * 30 + b"ID3\x04",
        b"MZ\x90\x00\x03" + b"\x00" * 30,
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 30,
        b"GIF89a" + b"\x00" * 30,
        b"\xff\xd8\xff\xe0" + b"\x00" * 30,
        b"\xff",
        b"RIFF\x00\x00\x00\x00AVI LIST",
        b"<html><script>alert(1)</script></html>",
    ],
)
def test_other_content_is_not_a_recognised_container(data: bytes) -> None:
    assert detect_container(data) is None


def test_isobmff_is_staged_to_a_seekable_file() -> None:
    assert needs_seekable_input(b"\x00\x00\x00\x20ftypM4A ")
    assert not needs_seekable_input(b"RIFF\x00\x00\x00\x00WAVE")
    assert not needs_seekable_input(b"")


def test_a_single_audio_stream_in_the_expected_container_passes() -> None:
    result = check_probe("wav", probe("wav", stream("audio")), 1234, LIMITS)

    assert (result.container, result.duration_ms, result.size_bytes, result.sample_rate, result.channels) == (
        "wav",
        5000,
        1234,
        44100,
        2,
    )


def test_probe_duration_is_used_when_the_stream_has_none() -> None:
    result = check_probe("mp3", probe("mp3", stream("audio", duration_ms=None), duration_ms=7000), 10, LIMITS)

    assert result.duration_ms == 7000


@pytest.mark.parametrize(
    ("container", "format_name", "streams", "code"),
    [
        ("mp3", "mp3", (stream("audio"), stream("video", 1)), "video_stream_present"),
        ("mp4", "mov,mp4,m4a,3gp,3g2,mj2", (stream("video"),), "video_stream_present"),
        ("wav", "wav", (), "not_audio"),
        ("wav", "wav", (stream("other"),), "not_audio"),
        ("mp4", "mov,mp4,m4a,3gp,3g2,mj2", (stream("audio"), stream("other", 1)), "unsupported_format"),
        ("mp4", "mov,mp4,m4a,3gp,3g2,mj2", (stream("audio"), stream("audio", 1)), "unsupported_format"),
        ("wav", "mp3", (stream("audio"),), "not_audio"),
    ],
)
def test_streams_and_container_mismatches_are_rejected_with_stable_codes(
    container: Container, format_name: str, streams: tuple[StreamInfo, ...], code: str
) -> None:
    with pytest.raises(AudioRejectedError) as raised:
        check_probe(container, probe(format_name, *streams), 10, LIMITS)

    assert raised.value.code == code


@pytest.mark.parametrize(
    ("duration_ms", "code"),
    [(999, "too_short"), (300_001, "too_long"), (None, "probe_failed"), (0, "probe_failed")],
)
def test_duration_limits(duration_ms: int | None, code: str) -> None:
    with pytest.raises(AudioRejectedError) as raised:
        check_probe("wav", probe("wav", stream("audio", duration_ms=duration_ms), duration_ms=duration_ms), 10, LIMITS)

    assert raised.value.code == code


def test_duration_boundaries_are_inclusive() -> None:
    assert check_probe("wav", probe("wav", stream("audio", duration_ms=1000)), 10, LIMITS).duration_ms == 1000
    assert check_probe("wav", probe("wav", stream("audio", duration_ms=300_000)), 10, LIMITS).duration_ms == 300_000


def test_wav_conversion_is_capped_in_duration_and_size() -> None:
    arguments = wav_arguments(30_000)

    assert arguments[arguments.index("-t") + 1] == "30.000"
    assert arguments[arguments.index("-ac") + 1] == "1"
    assert arguments[arguments.index("-ar") + 1] == "44100"
    assert arguments[arguments.index("-c:a") + 1] == "pcm_s16le"
    assert int(arguments[arguments.index("-fs") + 1]) < 30 * 44100 * 2 + 10_000
    assert arguments[-3:] == ["-f", "wav", "pipe:1"]
    assert "-vn" in arguments


def test_decode_check_stops_at_errors_and_caps_the_decoded_length() -> None:
    arguments = decode_check_arguments(LIMITS)

    assert arguments[0] == "-xerror"
    assert arguments[-3:] == ["-f", "s16le", "pipe:1"]
    assert arguments[arguments.index("-t") + 1] == "301"
