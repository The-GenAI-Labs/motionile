import re
from pathlib import Path

import pytest

from motionile.engine.audio.models import SynthesisOptions, VoiceRef, WordTiming
from motionile.engine.audio.narration import SceneAudio, assemble_narration
from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.audio.providers.fake import FakeTTSProvider
from motionile.engine.audio.subtitles import (
    CAPTION_LAYOUTS,
    Aspect,
    Cue,
    build_cues,
    render_ass,
    render_srt,
    render_webvtt,
)
from motionile.engine.ffmpeg import FfmpegTools, probe_file, run_ffmpeg

pytestmark = pytest.mark.slow

VOICE = VoiceRef("fake", "fake-voice-aria", "en")
OPTIONS = SynthesisOptions(language="en")
SCRIPT = [
    "Every video begins with a question. Why does the sky look blue during the day?",
    "Sunlight scatters off tiny molecules, and short blue wavelengths scatter the most.",
    "At sunset the light travels farther, so the reds and oranges remain.",
]
CUE_TIME = re.compile(r"(\d+):(\d{2}):(\d{2})\.(\d{3}) --> (\d+):(\d{2}):(\d{2})\.(\d{3})")


async def narrate() -> tuple[NarrationDocument, list[WordTiming], set[int]]:
    provider = FakeTTSProvider()
    scenes: list[SceneAudio] = []
    for index, text in enumerate(SCRIPT):
        result = await provider.synthesize(text, VOICE, OPTIONS)
        scenes.append(SceneAudio(f"s{index}", text, result.duration_ms, result.words))
    document = assemble_narration(scenes, 350)
    words: list[WordTiming] = []
    scene_starts: set[int] = set()
    for scene in document.scenes:
        scene_starts.add(len(words))
        words.extend(WordTiming(word.text, word.start_ms, word.end_ms) for word in scene.words)
    return document, words, scene_starts


def to_ms(hours: str, minutes: str, seconds: str, millis: str) -> int:
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(millis)


async def test_cue_times_match_the_narration_word_timings() -> None:
    _, words, scene_starts = await narrate()
    cues = build_cues(words, forced_breaks=scene_starts - {0})

    parsed = [CUE_TIME.search(block) for block in render_webvtt(cues).split("\n\n")[1:] if block.strip()]
    assert len(parsed) == len(cues)
    for cue, match in zip(cues, parsed, strict=True):
        assert match is not None
        start = to_ms(*match.groups()[:4])
        end = to_ms(*match.groups()[4:])
        assert (start, end) == (cue.start_ms, cue.end_ms)
        assert start == words[cue.first_word].start_ms
        assert end >= min(words[cue.end_word - 1].end_ms, start + 6000)
    for start in scene_starts - {0}:
        assert any(cue.first_word == start for cue in cues)
    assert [word for cue in cues for word in range(cue.first_word, cue.end_word)] == list(range(len(words)))


async def test_srt_and_webvtt_carry_the_same_cues() -> None:
    _, words, scene_starts = await narrate()
    cues = build_cues(words, forced_breaks=scene_starts - {0})

    vtt_blocks = render_webvtt(cues).strip().split("\n\n")[1:]
    vtt_text = [block.split("\n", 2)[2] for block in vtt_blocks]
    srt_text = [block.split("\n", 2)[2] for block in render_srt(cues).strip().split("\n\n")]

    assert vtt_text == [cue.text for cue in cues]
    assert srt_text == [cue.text for cue in cues]


async def render_frame(tools: FfmpegTools, aspect: Aspect, cue: Cue, ass_name: str) -> bytes:
    layout = CAPTION_LAYOUTS[aspect]
    middle = (cue.start_ms + cue.end_ms) / 2 / 1000
    result = await run_ffmpeg(
        tools,
        [
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={layout.width}x{layout.height}:r=10:d=30",
            "-vf",
            f"ass={ass_name}",
            "-ss",
            f"{middle:.3f}",
            "-frames:v",
            "1",
            "-pix_fmt",
            "gray",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        timeout_seconds=120,
    )
    return result.stdout


@pytest.mark.parametrize("aspect", ["16:9", "9:16", "1:1"])
async def test_ass_burns_inside_the_caption_band_at_native_resolution(tools: FfmpegTools, aspect: Aspect) -> None:
    _, words, scene_starts = await narrate()
    cues = build_cues(words, forced_breaks=scene_starts - {0})
    layout = CAPTION_LAYOUTS[aspect]
    ass_path = Path.cwd() / "captions.ass"
    ass_path.write_text(render_ass(cues, aspect), encoding="utf-8")

    frame = await render_frame(tools, aspect, cues[1], ass_path.name)

    assert len(frame) == layout.width * layout.height
    lit_rows = [row for row in range(layout.height) if any(frame[row * layout.width : (row + 1) * layout.width])]
    if not lit_rows:
        pytest.skip("libass found no system font to draw captions with")
    band_top = layout.height - layout.band_px
    assert min(lit_rows) >= band_top - 2
    assert max(lit_rows) < layout.height


async def test_probe_of_a_burned_clip_reports_the_aspect_resolution(tools: FfmpegTools, tmp_path: Path) -> None:
    _, words, scene_starts = await narrate()
    cues = build_cues(words, forced_breaks=scene_starts - {0})
    (Path.cwd() / "captions.ass").write_text(render_ass(cues, "9:16"), encoding="utf-8")
    output = tmp_path / "burned.mp4"

    await run_ffmpeg(
        tools,
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1080x1920:r=10:d=2",
            "-vf",
            "ass=captions.ass",
            "-c:v",
            "mpeg4",
            "-y",
            str(output),
        ],
        timeout_seconds=120,
    )

    video = (await probe_file(tools, output)).video_streams[0]
    assert (video.width, video.height) == (1080, 1920)
