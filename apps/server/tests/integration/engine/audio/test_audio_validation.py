import struct
from pathlib import Path

import pytest
from tests.integration.engine.audio.support import MediaFactory

from motionile.engine.audio.audio_validation import (
    AudioRejectedError,
    AudioUploadLimits,
    transcode_to_wav,
    validate_audio_upload,
)
from motionile.engine.ffmpeg import FfmpegTools, probe_file, run_ffmpeg

pytestmark = pytest.mark.slow

LIMITS = AudioUploadLimits(max_bytes=20_000_000, min_duration_ms=1000, max_duration_ms=120_000)
SINE = "sine=frequency=440:duration=3"
NOISE = "anoisesrc=duration=60:color=pink:amplitude=0.2"


async def rejection(tools: FfmpegTools, data: bytes, limits: AudioUploadLimits = LIMITS) -> str:
    with pytest.raises(AudioRejectedError) as raised:
        await validate_audio_upload(tools, data, limits)
    return raised.value.code


@pytest.mark.parametrize(
    ("name", "output_arguments", "expected"),
    [
        ("tone.wav", (), ("wav", "pcm_s16le")),
        ("tone.mp3", ("-c:a", "libmp3lame"), ("mp3", "mp3")),
        ("tone.m4a", ("-c:a", "aac"), ("mp4", "aac")),
        ("tone.ogg", ("-c:a", "libvorbis"), ("ogg", "vorbis")),
        ("tone.flac", (), ("flac", "flac")),
        ("tone.webm", ("-c:a", "libopus"), ("matroska", "opus")),
        ("tone.aac", ("-c:a", "aac", "-f", "adts"), ("aac", "aac")),
    ],
)
async def test_real_audio_containers_are_accepted(
    tools: FfmpegTools,
    media: MediaFactory,
    name: str,
    output_arguments: tuple[str, ...],
    expected: tuple[str, str],
) -> None:
    data = (await media.make(name, SINE, *output_arguments)).read_bytes()

    result = await validate_audio_upload(tools, data, LIMITS)

    assert (result.container, result.codec_name) == expected
    assert 2800 <= result.duration_ms <= 3200
    assert result.size_bytes == len(data)


async def test_large_isobmff_with_the_index_at_the_end_is_validated_and_converted(
    tools: FfmpegTools, media: MediaFactory
) -> None:
    data = (await media.make("long.m4a", NOISE, "-c:a", "aac", "-b:a", "256k")).read_bytes()
    assert len(data) > 1_000_000

    result = await validate_audio_upload(tools, data, LIMITS)
    wav = await transcode_to_wav(tools, data, max_duration_ms=120_000)

    assert result.container == "mp4"
    assert 59_000 <= result.duration_ms <= 61_000
    assert 59_000 <= wav.duration_ms <= 61_000


async def test_an_mp3_with_cover_art_has_a_video_stream_and_is_rejected(
    tools: FfmpegTools, media: MediaFactory
) -> None:
    cover = media.directory / "tone.mp3"
    await run_ffmpeg(
        tools,
        [
            "-f",
            "lavfi",
            "-i",
            SINE,
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=64x64:d=1",
            "-map",
            "0:a",
            "-map",
            "1:v",
            "-c:a",
            "libmp3lame",
            "-c:v",
            "mjpeg",
            "-frames:v",
            "1",
            "-disposition:v",
            "attached_pic",
            "-y",
            str(cover),
        ],
        timeout_seconds=60,
    )

    assert await rejection(tools, cover.read_bytes()) == "video_stream_present"


async def test_a_video_file_is_rejected(tools: FfmpegTools, media: MediaFactory) -> None:
    video = media.directory / "clip.mp4"
    await run_ffmpeg(
        tools,
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64:d=2",
            "-f",
            "lavfi",
            "-i",
            SINE,
            "-t",
            "2",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-y",
            str(video),
        ],
        timeout_seconds=60,
    )

    assert await rejection(tools, video.read_bytes()) == "video_stream_present"


async def test_text_renamed_to_mp3_is_not_audio(tools: FfmpegTools) -> None:
    assert await rejection(tools, b"This is definitely not an mp3 file.\n" * 500) == "not_audio"


async def test_zero_length_upload(tools: FfmpegTools) -> None:
    assert await rejection(tools, b"") == "not_audio"


@pytest.mark.parametrize(
    "prefix",
    [
        b"PK\x03\x04\x14\x00\x00\x00" + b"\x00" * 40,
        b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 60,
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 20,
        b"GIF89a\x01\x00\x01\x00" + b"\x00" * 20,
        b"%PDF-1.7\n" + b"\x00" * 20,
    ],
)
@pytest.mark.parametrize("name", ["tone.mp3", "tone.wav"])
async def test_polyglots_with_a_foreign_prefix_are_not_audio(
    tools: FfmpegTools, media: MediaFactory, prefix: bytes, name: str
) -> None:
    audio = (await media.make(name, SINE, *(("-c:a", "libmp3lame") if name.endswith("mp3") else ()))).read_bytes()

    assert await rejection(tools, prefix + audio) == "not_audio"


async def test_a_truncated_isobmff_file_is_rejected(tools: FfmpegTools, media: MediaFactory) -> None:
    data = (await media.make("long.m4a", NOISE, "-c:a", "aac")).read_bytes()

    assert await rejection(tools, data[: len(data) // 2]) in {"probe_failed", "not_audio"}


async def test_a_header_only_file_is_rejected(tools: FfmpegTools, media: MediaFactory) -> None:
    data = (await media.make("tone.flac", SINE)).read_bytes()

    assert await rejection(tools, data[:20]) in {"probe_failed", "not_audio"}


async def test_garbage_after_a_valid_signature_is_rejected(tools: FfmpegTools) -> None:
    assert await rejection(tools, b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\xde\xad\xbe\xef" * 200) in {
        "probe_failed",
        "not_audio",
    }
    assert await rejection(tools, b"OggS" + b"\x13\x37" * 300) in {"probe_failed", "not_audio"}


async def test_oversize_files_are_rejected_before_probing(tools: FfmpegTools, media: MediaFactory) -> None:
    data = (await media.make("tone.wav", SINE)).read_bytes()

    assert await rejection(tools, data, AudioUploadLimits(len(data) - 1, 1000, 120_000)) == "too_large"
    assert (await validate_audio_upload(tools, data, AudioUploadLimits(len(data), 1000, 120_000))).size_bytes == len(
        data
    )


async def test_duration_limits(tools: FfmpegTools, media: MediaFactory) -> None:
    data = (await media.make("tone.wav", SINE)).read_bytes()

    assert await rejection(tools, data, AudioUploadLimits(10_000_000, 5000, 120_000)) == "too_short"
    assert await rejection(tools, data, AudioUploadLimits(10_000_000, 500, 2000)) == "too_long"


async def test_validation_never_reads_local_files_through_a_playlist(tools: FfmpegTools, tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")
    playlist = f"#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nfile:{secret.as_posix()}\n#EXT-X-ENDLIST\n".encode()

    assert await rejection(tools, playlist) == "not_audio"


@pytest.mark.parametrize(
    ("name", "output_arguments"),
    [
        ("tone.mp3", ("-c:a", "libmp3lame")),
        ("tone.m4a", ("-c:a", "aac")),
        ("tone.flac", ()),
        ("tone.webm", ("-c:a", "libopus")),
    ],
)
async def test_transcode_produces_a_mono_44k_wav_with_correct_header_sizes(
    tools: FfmpegTools, media: MediaFactory, name: str, output_arguments: tuple[str, ...]
) -> None:
    original = (await media.make(name, SINE, *output_arguments)).read_bytes()

    wav = await transcode_to_wav(tools, original, max_duration_ms=120_000)

    assert wav.data[:4] == b"RIFF"
    assert struct.unpack("<I", wav.data[4:8])[0] == len(wav.data) - 8
    assert original not in wav.data
    written = media.directory / "converted.wav"
    written.write_bytes(wav.data)
    probe = await probe_file(tools, written)
    stream = probe.audio_streams[0]
    assert (stream.codec_name, stream.sample_rate, stream.channels) == ("pcm_s16le", 44100, 1)
    assert 2800 <= wav.duration_ms <= 3200
    assert probe.duration_ms is not None
    assert abs(probe.duration_ms - wav.duration_ms) <= 5


async def test_transcode_caps_the_duration(tools: FfmpegTools, media: MediaFactory) -> None:
    data = (await media.make("long.wav", NOISE)).read_bytes()

    wav = await transcode_to_wav(tools, data, max_duration_ms=5000)

    assert 4900 <= wav.duration_ms <= 5100


async def test_transcode_of_garbage_fails_with_a_stable_error(tools: FfmpegTools) -> None:
    with pytest.raises(AudioRejectedError) as raised:
        await transcode_to_wav(tools, b"not audio at all" * 100, max_duration_ms=5000)

    assert raised.value.code == "probe_failed"
