from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from motionile.engine.audio.models import WordTiming
from motionile.engine.audio.narration_models import NarrationDocument, NarrationScene, NarrationWord
from motionile.engine.audio.sources import ALLOWED_DEMUXERS, staged_source
from motionile.engine.audio.timing import clamp_words
from motionile.engine.ffmpeg import FfmpegError, FfmpegTools, probe_file, run_ffmpeg

NORMALIZED_SAMPLE_RATE = 48_000
NORMALIZE_TIMEOUT_SECONDS = 120.0
MAX_PADDING_MS = 10_000


class NarrationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SceneAudio:
    id: str
    text: str
    duration_ms: int
    words: tuple[WordTiming, ...]
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class NormalizedAudio:
    path: Path
    duration_ms: int


def scene_words(scene: SceneAudio, scene_start_ms: int) -> tuple[NarrationWord, ...]:
    spoken = [word for word in scene.words if word.text.strip()]
    clamped = clamp_words(spoken, scene.duration_ms)
    return tuple(
        NarrationWord(
            index=index,
            text=word.text,
            start_ms=scene_start_ms + word.start_ms,
            end_ms=scene_start_ms + word.end_ms,
            scene_start_ms=word.start_ms,
            scene_end_ms=word.end_ms,
        )
        for index, word in enumerate(clamped)
    )


def assemble_narration(scenes: Sequence[SceneAudio], padding_ms: int) -> NarrationDocument:
    if not scenes:
        raise NarrationError("a narration needs at least one scene")
    if not 0 <= padding_ms <= MAX_PADDING_MS:
        raise NarrationError("the scene padding is out of range")
    identifiers = [scene.id for scene in scenes]
    if len(set(identifiers)) != len(identifiers):
        raise NarrationError("scene identifiers must be unique")
    assembled: list[NarrationScene] = []
    cursor = 0
    last_index = len(scenes) - 1
    for index, scene in enumerate(scenes):
        if scene.duration_ms <= 0:
            raise NarrationError(f"scene {scene.id} has no audio")
        duration = scene.duration_ms + (padding_ms if index < last_index else 0)
        assembled.append(
            NarrationScene(
                id=scene.id,
                index=index,
                start_ms=cursor,
                duration_ms=duration,
                text=scene.text,
                words=scene_words(scene, cursor),
            )
        )
        cursor += duration
    return NarrationDocument(total_duration_ms=cursor, scenes=tuple(assembled))


def normalize_arguments(destination: Path) -> list[str]:
    return [
        "-vn",
        "-map",
        "0:a:0",
        "-map_metadata",
        "-1",
        "-ac",
        "1",
        "-ar",
        str(NORMALIZED_SAMPLE_RATE),
        "-c:a",
        "pcm_s16le",
        "-y",
        str(destination),
    ]


async def measure_wav_duration_ms(tools: FfmpegTools, path: Path) -> int:
    probe = await probe_file(tools, path)
    streams = probe.audio_streams
    duration = (streams[0].duration_ms if streams else None) or probe.duration_ms
    if duration is None:
        raise FfmpegError("the normalized audio has no duration")
    return duration


async def normalize_scene_audio(
    tools: FfmpegTools,
    source: bytes | Path,
    destination: Path,
    *,
    timeout_seconds: float = NORMALIZE_TIMEOUT_SECONDS,
) -> NormalizedAudio:
    async with staged_source(source, formats=ALLOWED_DEMUXERS) as resolved:
        await run_ffmpeg(
            tools,
            [*resolved.arguments, *normalize_arguments(destination)],
            timeout_seconds=timeout_seconds,
            stdin=resolved.stdin,
        )
    return NormalizedAudio(destination, await measure_wav_duration_ms(tools, destination))
