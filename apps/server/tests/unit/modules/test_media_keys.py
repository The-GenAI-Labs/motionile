from uuid import UUID

import pytest

from motionile.core.storage.base import validate_key
from motionile.modules.media.domain import Aspect
from motionile.modules.media.keys import (
    aspect_slug,
    composition_key,
    consent_recording_key,
    mixed_audio_key,
    music_key,
    poster_key,
    render_media_prefix,
    render_work_key,
    render_work_prefix,
    rendition_key,
    subtitles_key,
    tts_key,
    user_media_prefix,
    voice_prefix,
    voice_preview_key,
    voice_sample_key,
)

USER = UUID("0199eb00-0000-7000-8000-0000000000a1")
RENDER = UUID("0199eb00-0000-7000-8000-0000000000b2")
VOICE = UUID("0199eb00-0000-7000-8000-0000000000c3")
TRACK = UUID("0199eb00-0000-7000-8000-0000000000d4")
HASH = "ab" + "0123456789abcdef" * 3 + "cdcdcdcdcdcdcd"
RENDER_PREFIX = f"media/u/{USER}/renders/{RENDER}/"


def all_keys() -> list[str]:
    return [
        rendition_key(USER, RENDER, Aspect.LANDSCAPE),
        rendition_key(USER, RENDER, Aspect.PORTRAIT),
        rendition_key(USER, RENDER, Aspect.SQUARE),
        poster_key(USER, RENDER, Aspect.LANDSCAPE, "webp"),
        poster_key(USER, RENDER, "9:16", "jpg"),
        subtitles_key(USER, RENDER, "vtt"),
        subtitles_key(USER, RENDER, "srt"),
        mixed_audio_key(USER, RENDER),
        composition_key(USER, RENDER),
        render_work_key(RENDER, "composition.clean.html"),
        render_work_key(RENDER, "segments", "16x9", "0003.mp4"),
        voice_sample_key(USER, VOICE, 0),
        consent_recording_key(USER, VOICE),
        tts_key(HASH, "mp3"),
        music_key(TRACK, "m4a"),
        voice_preview_key(VOICE),
    ]


def test_hash_fixture_is_a_sha256_hex_digest() -> None:
    assert len(HASH) == 64
    int(HASH, 16)


@pytest.mark.parametrize(
    ("value", "slug"),
    [
        (Aspect.LANDSCAPE, "16x9"),
        (Aspect.PORTRAIT, "9x16"),
        (Aspect.SQUARE, "1x1"),
        ("16:9", "16x9"),
        ("9:16", "9x16"),
        ("1:1", "1x1"),
        ("16x9", "16x9"),
        ("1x1", "1x1"),
    ],
)
def test_aspect_slugs_replace_the_colon(value: Aspect | str, slug: str) -> None:
    assert aspect_slug(value) == slug


@pytest.mark.parametrize("value", ["4:3", "", "16/9", "wide"])
def test_unknown_aspects_are_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="is not a valid Aspect"):
        aspect_slug(value)


def test_every_key_passes_the_storage_key_validation() -> None:
    for key in all_keys():
        assert validate_key(key) == key


def test_prefixes_end_with_a_slash_and_are_valid_when_trimmed() -> None:
    for prefix in (
        user_media_prefix(USER),
        render_media_prefix(USER, RENDER),
        render_work_prefix(RENDER),
        voice_prefix(USER, VOICE),
    ):
        assert prefix.endswith("/")
        validate_key(prefix.rstrip("/"))


def test_the_documented_layout_is_produced() -> None:
    assert user_media_prefix(USER) == f"media/u/{USER}/"
    assert render_media_prefix(USER, RENDER) == RENDER_PREFIX
    assert rendition_key(USER, RENDER, Aspect.LANDSCAPE) == f"{RENDER_PREFIX}16x9.mp4"
    assert rendition_key(USER, RENDER, Aspect.PORTRAIT) == f"{RENDER_PREFIX}9x16.mp4"
    assert rendition_key(USER, RENDER, Aspect.SQUARE) == f"{RENDER_PREFIX}1x1.mp4"
    assert poster_key(USER, RENDER, Aspect.PORTRAIT, "webp") == f"{RENDER_PREFIX}poster-9x16.webp"
    assert poster_key(USER, RENDER, Aspect.SQUARE, "jpg") == f"{RENDER_PREFIX}poster-1x1.jpg"
    assert subtitles_key(USER, RENDER, "vtt") == f"{RENDER_PREFIX}subtitles.vtt"
    assert subtitles_key(USER, RENDER, "srt") == f"{RENDER_PREFIX}subtitles.srt"
    assert mixed_audio_key(USER, RENDER) == f"{RENDER_PREFIX}audio.m4a"
    assert composition_key(USER, RENDER) == f"{RENDER_PREFIX}composition.html"
    assert render_work_prefix(RENDER) == f"work/renders/{RENDER}/"
    assert render_work_key(RENDER, "segments", "16x9", "0001.mp4") == f"work/renders/{RENDER}/segments/16x9/0001.mp4"
    assert voice_prefix(USER, VOICE) == f"voice/u/{USER}/{VOICE}/"
    assert voice_sample_key(USER, VOICE, 2) == f"voice/u/{USER}/{VOICE}/sample-2.wav"
    assert consent_recording_key(USER, VOICE) == f"voice/u/{USER}/{VOICE}/consent.wav"
    assert tts_key(HASH, "mp3") == f"tts/ab/{HASH}.mp3"
    assert music_key(TRACK, "m4a") == f"music/{TRACK}.m4a"
    assert voice_preview_key(VOICE) == f"voice-preview/{VOICE}.mp3"


def test_only_render_outputs_live_under_the_cdn_prefix() -> None:
    served = [key for key in all_keys() if key.startswith("media/")]

    assert served
    assert all(key.startswith(user_media_prefix(USER)) for key in served)
    assert {key.split("/", 1)[0] for key in all_keys() if key not in served} == {
        "work",
        "voice",
        "tts",
        "music",
        "voice-preview",
    }


def test_no_key_outside_media_can_start_with_media() -> None:
    private = [
        render_work_key(RENDER, "media", "x"),
        render_work_prefix(RENDER),
        voice_prefix(USER, VOICE),
        voice_sample_key(USER, VOICE, 0),
        consent_recording_key(USER, VOICE),
        tts_key(HASH, "mp3"),
        music_key(TRACK, "m4a"),
        voice_preview_key(VOICE),
    ]

    assert not any(key.startswith("media/") for key in private)


def test_media_keys_never_leave_their_users_prefix() -> None:
    other = UUID("0199eb00-0000-7000-8000-0000000000ff")

    assert not rendition_key(USER, RENDER, Aspect.LANDSCAPE).startswith(user_media_prefix(other))
    assert not user_media_prefix(USER).startswith(user_media_prefix(other))


@pytest.mark.parametrize("ext", ["", "MP4", "mp4/", ".mp4", "m p4", "waytoolongext", "../x"])
def test_invalid_extensions_are_rejected(ext: str) -> None:
    with pytest.raises(ValueError, match="invalid file extension"):
        subtitles_key(USER, RENDER, ext)
    with pytest.raises(ValueError, match="invalid file extension"):
        poster_key(USER, RENDER, Aspect.LANDSCAPE, ext)
    with pytest.raises(ValueError, match="invalid file extension"):
        music_key(TRACK, ext)


@pytest.mark.parametrize("part", ["", "..", "a/b", "/abs", "-start", "sp ace", "a" * 129, "x..y", "back\\slash"])
def test_work_key_parts_are_validated(part: str) -> None:
    with pytest.raises(ValueError, match="invalid key segment"):
        render_work_key(RENDER, "segments", part)


def test_a_work_key_needs_parts() -> None:
    with pytest.raises(ValueError, match="at least one part"):
        render_work_key(RENDER)


@pytest.mark.parametrize("value", ["", "AB" * 32, "ab" * 31, "ab" * 33, "zz" * 32, "../" + "a" * 61])
def test_tts_keys_need_a_lowercase_sha256_hex_digest(value: str) -> None:
    with pytest.raises(ValueError, match="64 lowercase hexadecimal"):
        tts_key(value, "mp3")


def test_sample_indexes_cannot_be_negative() -> None:
    with pytest.raises(ValueError, match="negative"):
        voice_sample_key(USER, VOICE, -1)
