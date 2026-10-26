import re
from uuid import UUID

from motionile.core.storage.base import validate_key
from motionile.modules.media.domain import Aspect

MEDIA_ROOT = "media"
WORK_ROOT = "work"
VOICE_ROOT = "voice"
TTS_ROOT = "tts"
MUSIC_ROOT = "music"
VOICE_PREVIEW_ROOT = "voice-preview"
EXTENSION_PATTERN = re.compile(r"^[a-z0-9]{1,8}$")
SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
CONTENT_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
HASH_PREFIX_LENGTH = 2
SLUGS = {aspect.slug: aspect for aspect in Aspect}


def aspect_slug(aspect: Aspect | str) -> str:
    if isinstance(aspect, Aspect):
        return aspect.slug
    if aspect in SLUGS:
        return aspect
    return Aspect(aspect).slug


def extension(value: str) -> str:
    if EXTENSION_PATTERN.fullmatch(value) is None:
        raise ValueError(f"invalid file extension {value!r}")
    return value


def segment(value: str) -> str:
    if SEGMENT_PATTERN.fullmatch(value) is None or ".." in value:
        raise ValueError(f"invalid key segment {value!r}")
    return value


def user_media_prefix(user_id: UUID) -> str:
    return validate_key(f"{MEDIA_ROOT}/u/{user_id}") + "/"


def render_media_prefix(user_id: UUID, render_id: UUID) -> str:
    return validate_key(f"{MEDIA_ROOT}/u/{user_id}/renders/{render_id}") + "/"


def rendition_key(user_id: UUID, render_id: UUID, aspect: Aspect | str) -> str:
    return validate_key(f"{render_media_prefix(user_id, render_id)}{aspect_slug(aspect)}.mp4")


def poster_key(user_id: UUID, render_id: UUID, aspect: Aspect | str, ext: str) -> str:
    return validate_key(f"{render_media_prefix(user_id, render_id)}poster-{aspect_slug(aspect)}.{extension(ext)}")


def subtitles_key(user_id: UUID, render_id: UUID, ext: str) -> str:
    return validate_key(f"{render_media_prefix(user_id, render_id)}subtitles.{extension(ext)}")


def mixed_audio_key(user_id: UUID, render_id: UUID) -> str:
    return validate_key(f"{render_media_prefix(user_id, render_id)}audio.m4a")


def composition_key(user_id: UUID, render_id: UUID) -> str:
    return validate_key(f"{render_media_prefix(user_id, render_id)}composition.html")


def render_work_prefix(render_id: UUID) -> str:
    return validate_key(f"{WORK_ROOT}/renders/{render_id}") + "/"


def render_work_key(render_id: UUID, *parts: str) -> str:
    if not parts:
        raise ValueError("a work key needs at least one part")
    return validate_key(render_work_prefix(render_id) + "/".join(segment(part) for part in parts))


def composition_check_prefix(job_id: UUID, check_id: str) -> str:
    return validate_key(f"{WORK_ROOT}/jobs/{job_id}/checks/{segment(check_id)}") + "/"


def composition_check_key(job_id: UUID, check_id: str, *parts: str) -> str:
    if not parts:
        raise ValueError("a composition check key needs at least one part")
    return validate_key(composition_check_prefix(job_id, check_id) + "/".join(segment(part) for part in parts))


def user_voice_prefix(user_id: UUID) -> str:
    return validate_key(f"{VOICE_ROOT}/u/{user_id}") + "/"


def voice_prefix(user_id: UUID, voice_id: UUID) -> str:
    return validate_key(f"{VOICE_ROOT}/u/{user_id}/{voice_id}") + "/"


def voice_sample_key(user_id: UUID, voice_id: UUID, index: int, ext: str = "wav") -> str:
    if index < 0:
        raise ValueError("sample index must not be negative")
    return validate_key(f"{voice_prefix(user_id, voice_id)}sample-{index}.{extension(ext)}")


def consent_recording_key(user_id: UUID, voice_id: UUID, ext: str = "wav") -> str:
    return validate_key(f"{voice_prefix(user_id, voice_id)}consent.{extension(ext)}")


def tts_key(content_hash_hex: str, ext: str) -> str:
    if CONTENT_HASH_PATTERN.fullmatch(content_hash_hex) is None:
        raise ValueError("content hash must be 64 lowercase hexadecimal characters")
    return validate_key(f"{TTS_ROOT}/{content_hash_hex[:HASH_PREFIX_LENGTH]}/{content_hash_hex}.{extension(ext)}")


def music_key(track_id: UUID, ext: str) -> str:
    return validate_key(f"{MUSIC_ROOT}/{track_id}.{extension(ext)}")


def voice_preview_key(voice_id: UUID, ext: str = "mp3") -> str:
    return validate_key(f"{VOICE_PREVIEW_ROOT}/{voice_id}.{extension(ext)}")
