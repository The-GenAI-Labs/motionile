from fractions import Fraction
from typing import Any

from motionile.engine.ffmpeg import fraction_or_none, parse_probe, seconds_to_ms

VIDEO_DOCUMENT: dict[str, Any] = {
    "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "2.500000", "size": "48213"},
    "streams": [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": "h264",
            "profile": "High",
            "width": 1920,
            "height": 1080,
            "pix_fmt": "yuv420p",
            "color_space": "bt709",
            "color_primaries": "bt709",
            "color_transfer": "bt709",
            "color_range": "tv",
            "avg_frame_rate": "30/1",
            "nb_read_frames": "75",
            "duration": "2.500000",
        },
        {
            "index": 1,
            "codec_type": "audio",
            "codec_name": "aac",
            "sample_rate": "48000",
            "channels": 2,
            "duration": "2.490000",
            "bit_rate": "192000",
        },
        {"index": 2, "codec_type": "data"},
    ],
}


def test_parse_probe_reads_format_and_streams() -> None:
    probe = parse_probe(VIDEO_DOCUMENT)

    assert probe.duration_ms == 2500
    assert probe.size_bytes == 48213
    assert len(probe.video_streams) == 1
    assert len(probe.audio_streams) == 1
    video = probe.video_streams[0]
    assert (video.width, video.height, video.pix_fmt, video.profile) == (1920, 1080, "yuv420p", "High")
    assert video.frame_count == 75
    assert video.frame_rate == Fraction(30)
    assert (video.color_space, video.color_primaries, video.color_transfer, video.color_range) == (
        "bt709",
        "bt709",
        "bt709",
        "tv",
    )
    audio = probe.audio_streams[0]
    assert (audio.sample_rate, audio.channels, audio.duration_ms, audio.bit_rate) == (48000, 2, 2490, 192000)
    assert probe.streams[2].kind == "other"


def test_parse_probe_tolerates_missing_fields() -> None:
    probe = parse_probe({"streams": [{"codec_type": "audio"}]})

    assert probe.format_name == ""
    assert probe.duration_ms is None
    assert probe.streams[0].sample_rate is None


def test_seconds_to_ms_rounds_and_rejects_garbage() -> None:
    assert seconds_to_ms("1.0005") == 1000
    assert seconds_to_ms("N/A") is None
    assert seconds_to_ms(None) is None


def test_fraction_or_none_rejects_zero_denominator_and_zero_rate() -> None:
    assert fraction_or_none("30000/1001") == Fraction(30000, 1001)
    assert fraction_or_none("0/0") is None
    assert fraction_or_none("0/1") is None
    assert fraction_or_none("30") is None
