import dataclasses
import re
from pathlib import Path

import pytest
from tests.integration.engine.audio.support import MediaFactory

from motionile.engine.audio.mix import (
    LoudnessReport,
    MixPlan,
    MusicBed,
    measure_loudness,
    mix_audio,
    run_with_report,
    transcode_music,
)
from motionile.engine.audio.models import SynthesisOptions, VoiceRef
from motionile.engine.audio.narration import (
    NormalizedAudio,
    SceneAudio,
    assemble_narration,
    normalize_scene_audio,
)
from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.audio.providers.fake import FakeTTSProvider
from motionile.engine.audio.sources import file_input
from motionile.engine.audio.wav import parse_wav
from motionile.engine.ffmpeg import FfmpegTools, probe_file, run_ffmpeg

pytestmark = pytest.mark.slow

VOICE = VoiceRef("fake", "fake-voice-aria", "en")
OPTIONS = SynthesisOptions(language="en")
TEXTS = ["alpha beta gamma delta", "epsilon zeta theta iota"]
PADDING_MS = 2000
TAIL_MS = 1000
MUSIC_HZ = 2000
MEAN_VOLUME = re.compile(r"mean_volume:\s+(-?\d+(?:\.\d+)?|-inf)\s+dB")


async def prepare_scenes(
    tools: FfmpegTools, directory: Path, texts: list[str], *, tone: bool = True
) -> tuple[list[SceneAudio], NarrationDocument]:
    provider = FakeTTSProvider(tone=tone)
    scenes: list[SceneAudio] = []
    for index, text in enumerate(texts):
        result = await provider.synthesize(text, VOICE, OPTIONS)
        normalized: NormalizedAudio = await normalize_scene_audio(tools, result.audio, directory / f"scene-{index}.wav")
        scenes.append(SceneAudio(f"s{index}", text, normalized.duration_ms, result.words, normalized.path))
    return scenes, assemble_narration(scenes, PADDING_MS)


def plan_for(scenes: list[SceneAudio], document: NarrationDocument, music: MusicBed | None = None) -> MixPlan:
    paths = tuple(scene.path for scene in scenes if scene.path is not None)
    return MixPlan(
        scene_paths=paths,
        padding_ms=PADDING_MS,
        total_ms=document.total_duration_ms + TAIL_MS,
        tail_ms=TAIL_MS,
        music=music,
    )


async def make_music(tools: FfmpegTools, media: MediaFactory) -> Path:
    source = await media.make("music-source.wav", f"sine=frequency={MUSIC_HZ}:duration=2.5:sample_rate=44100")
    return await transcode_music(tools, source.read_bytes(), media.directory / "music.m4a")


async def band_level_db(tools: FfmpegTools, path: Path, start_s: float, length_s: float) -> float:
    arguments = [
        "-ss",
        f"{start_s:.3f}",
        "-t",
        f"{length_s:.3f}",
        *file_input(path),
        "-af",
        f"bandpass=f={MUSIC_HZ}:width_type=h:w=200,volumedetect",
        "-f",
        "null",
        "-",
    ]
    report = await run_with_report(tools, arguments, timeout_seconds=60)
    match = MEAN_VOLUME.search(report)
    assert match is not None
    return float(match.group(1))


def assert_on_target(report: LoudnessReport) -> None:
    assert abs(report.integrated_lufs - -16.0) <= 1.0, report
    assert report.true_peak_dbtp <= -1.0, report


async def assert_aac_48k_stereo(tools: FfmpegTools, path: Path, expected_ms: int) -> None:
    probe = await probe_file(tools, path)
    stream = probe.audio_streams[0]
    assert stream.codec_name == "aac"
    assert stream.sample_rate == 48000
    assert stream.channels == 2
    assert len(probe.streams) == 1
    assert probe.duration_ms is not None
    assert abs(probe.duration_ms - expected_ms) <= 100


async def test_normalizing_scene_audio_yields_48k_mono_16_bit_wav(tools: FfmpegTools, tmp_path: Path) -> None:
    result = await FakeTTSProvider().synthesize("hello brave new world", VOICE, OPTIONS)

    normalized = await normalize_scene_audio(tools, result.audio, tmp_path / "scene.wav")

    probe = await probe_file(tools, normalized.path)
    stream = probe.audio_streams[0]
    assert (stream.codec_name, stream.sample_rate, stream.channels) == ("pcm_s16le", 48000, 1)
    assert abs(normalized.duration_ms - result.duration_ms) <= 2
    assert parse_wav(normalized.path.read_bytes()).sample_rate == 48000


async def test_normalizing_accepts_other_inputs(tools: FfmpegTools, media: MediaFactory, tmp_path: Path) -> None:
    mp3 = await media.make("voice.mp3", "sine=frequency=300:duration=1.5", "-c:a", "libmp3lame", "-ac", "2")
    m4a = await media.make("voice.m4a", "sine=frequency=300:duration=1.5", "-c:a", "aac")

    from_bytes = await normalize_scene_audio(tools, mp3.read_bytes(), tmp_path / "a.wav")
    from_isobmff = await normalize_scene_audio(tools, m4a.read_bytes(), tmp_path / "b.wav")
    from_path = await normalize_scene_audio(tools, m4a, tmp_path / "c.wav")

    for normalized in (from_bytes, from_isobmff, from_path):
        stream = (await probe_file(tools, normalized.path)).audio_streams[0]
        assert (stream.sample_rate, stream.channels) == (48000, 1)
        assert 1400 <= normalized.duration_ms <= 1700


async def test_voice_only_mix_meets_the_loudness_targets_and_is_aac_48k(tools: FfmpegTools, tmp_path: Path) -> None:
    scenes, document = await prepare_scenes(tools, tmp_path, TEXTS)
    plan = plan_for(scenes, document)

    result = await mix_audio(tools, plan, tmp_path / "audio.m4a")

    assert result.normalized
    await assert_aac_48k_stereo(tools, result.path, plan.total_ms)
    assert_on_target(await measure_loudness(tools, result.path))


async def test_quiet_and_loud_sources_land_on_the_same_loudness(tools: FfmpegTools, tmp_path: Path) -> None:
    scenes, document = await prepare_scenes(tools, tmp_path, TEXTS)
    quiet_directory = tmp_path / "quiet"
    quiet_directory.mkdir()
    quiet_scenes: list[SceneAudio] = []
    for scene in scenes:
        assert scene.path is not None
        target = quiet_directory / scene.path.name
        await run_ffmpeg(tools, [*file_input(scene.path), "-af", "volume=-22dB", "-y", str(target)], timeout_seconds=60)
        quiet_scenes.append(dataclasses.replace(scene, path=target))

    loud = await measure_loudness(tools, (await mix_audio(tools, plan_for(scenes, document), tmp_path / "a.m4a")).path)
    quiet = await measure_loudness(
        tools, (await mix_audio(tools, plan_for(quiet_scenes, document), tmp_path / "b.m4a")).path
    )

    assert_on_target(loud)
    assert_on_target(quiet)
    assert abs(loud.integrated_lufs - quiet.integrated_lufs) <= 0.5


async def test_voice_with_music_meets_targets_and_ducks_the_music_under_speech(
    tools: FfmpegTools, media: MediaFactory, tmp_path: Path
) -> None:
    scenes, document = await prepare_scenes(tools, tmp_path, TEXTS)
    music = await make_music(tools, media)
    plan = plan_for(scenes, document, MusicBed(music))

    result = await mix_audio(tools, plan, tmp_path / "audio.m4a")

    await assert_aac_48k_stereo(tools, result.path, plan.total_ms)
    assert_on_target(await measure_loudness(tools, result.path))
    first = document.scenes[0]
    speech_end = first.start_ms + scenes[0].duration_ms
    during_speech = await band_level_db(tools, result.path, 1.1, (speech_end - 100) / 1000 - 1.1)
    in_gap = await band_level_db(tools, result.path, (speech_end + 1100) / 1000, 0.8)
    assert in_gap - during_speech >= 6.0, (during_speech, in_gap)


async def test_music_fades_out_over_the_tail(tools: FfmpegTools, media: MediaFactory, tmp_path: Path) -> None:
    scenes, document = await prepare_scenes(tools, tmp_path, TEXTS)
    music = await make_music(tools, media)
    plan = plan_for(scenes, document, MusicBed(music))

    result = await mix_audio(tools, plan, tmp_path / "audio.m4a")

    total_s = plan.total_ms / 1000
    early_tail = await band_level_db(tools, result.path, total_s - 1.0, 0.25)
    late_tail = await band_level_db(tools, result.path, total_s - 0.3, 0.25)
    assert late_tail < early_tail - 6.0


async def test_silent_voice_is_encoded_without_loudness_normalization(tools: FfmpegTools, tmp_path: Path) -> None:
    scenes, document = await prepare_scenes(tools, tmp_path, TEXTS, tone=False)
    plan = plan_for(scenes, document)

    result = await mix_audio(tools, plan, tmp_path / "audio.m4a")

    assert not result.normalized
    await assert_aac_48k_stereo(tools, result.path, plan.total_ms)


async def test_single_scene_mix(tools: FfmpegTools, tmp_path: Path) -> None:
    scenes, _ = await prepare_scenes(tools, tmp_path, [TEXTS[0]])
    document = assemble_narration(scenes, PADDING_MS)
    plan = plan_for(scenes, document)

    result = await mix_audio(tools, plan, tmp_path / "audio.m4a")

    await assert_aac_48k_stereo(tools, result.path, plan.total_ms)
    assert_on_target(await measure_loudness(tools, result.path))


async def test_transcoded_music_is_aac_stereo_48k_at_256k(tools: FfmpegTools, media: MediaFactory) -> None:
    source = await media.make(
        "bed.mp3", "anoisesrc=duration=4:color=pink:amplitude=0.2", "-c:a", "libmp3lame", "-ar", "44100"
    )

    output = await transcode_music(tools, source.read_bytes(), media.directory / "bed.m4a")

    stream = (await probe_file(tools, output)).audio_streams[0]
    assert (stream.codec_name, stream.sample_rate, stream.channels) == ("aac", 48000, 2)
    assert stream.bit_rate is not None
    assert 200_000 <= stream.bit_rate <= 300_000


async def test_loudness_measurement_reports_integrated_peak_and_range(tools: FfmpegTools, media: MediaFactory) -> None:
    quiet = await media.make("quiet.wav", "sine=frequency=1000:duration=5", "-af", "volume=-30dB")
    loud = await media.make("loud.wav", "sine=frequency=1000:duration=5", "-af", "volume=-12dB")

    quiet_report = await measure_loudness(tools, quiet)
    loud_report = await measure_loudness(tools, loud)

    assert loud_report.integrated_lufs - quiet_report.integrated_lufs == pytest.approx(18.0, abs=0.5)
    assert loud_report.true_peak_dbtp == pytest.approx(-30.0, abs=0.6)
    assert loud_report.loudness_range < 1.0
