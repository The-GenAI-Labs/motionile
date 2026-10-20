from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from motionile.engine.audio.narration_models import NarrationDocument, NarrationScene, NarrationWord
from motionile.engine.ffmpeg import FfmpegTools, run_ffmpeg

BASE_WORD_MS = 240
PER_CHARACTER_MS = 28
SCENE_LEAD_OUT_MS = 350
SCENE_PADDING_MS = 400
TONE_TIMEOUT_SECONDS = 120.0
TONE_FREQUENCY_HZ = 220
TONE_VOLUME = 0.2


@dataclass(frozen=True)
class SyntheticScene:
    scene_id: str
    text: str


def word_duration_ms(word: str) -> int:
    return BASE_WORD_MS + PER_CHARACTER_MS * len(word)


def build_scene(index: int, scene: SyntheticScene, start_ms: int, *, is_last: bool, padding_ms: int) -> NarrationScene:
    words: list[NarrationWord] = []
    cursor = 0
    for word_index, text in enumerate(scene.text.split()):
        duration = word_duration_ms(text)
        words.append(
            NarrationWord(
                index=word_index,
                text=text,
                start_ms=start_ms + cursor,
                end_ms=start_ms + cursor + duration,
                scene_start_ms=cursor,
                scene_end_ms=cursor + duration,
            )
        )
        cursor += duration
    audio_ms = cursor + SCENE_LEAD_OUT_MS
    return NarrationScene(
        id=scene.scene_id,
        index=index,
        start_ms=start_ms,
        duration_ms=audio_ms + (0 if is_last else padding_ms),
        text=scene.text,
        words=tuple(words),
    )


def build_synthetic_narration(
    scenes: Sequence[SyntheticScene],
    *,
    padding_ms: int = SCENE_PADDING_MS,
) -> NarrationDocument:
    built: list[NarrationScene] = []
    cursor = 0
    for index, scene in enumerate(scenes):
        item = build_scene(index, scene, cursor, is_last=index == len(scenes) - 1, padding_ms=padding_ms)
        built.append(item)
        cursor += item.duration_ms
    return NarrationDocument(total_duration_ms=cursor, scenes=tuple(built))


async def synthesize_tone(tools: FfmpegTools, output: Path, duration_ms: int) -> Path:
    seconds = f"{duration_ms / 1000:.3f}"
    await run_ffmpeg(
        tools,
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={TONE_FREQUENCY_HZ}:sample_rate=48000:duration={seconds}",
            "-af",
            f"volume={TONE_VOLUME}",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-t",
            seconds,
            "-f",
            "ipod",
            str(output),
        ],
        timeout_seconds=TONE_TIMEOUT_SECONDS,
    )
    return output
