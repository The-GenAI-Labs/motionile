from pathlib import Path

import pytest

from motionile.engine.audio.mix import (
    DuckingSettings,
    LoudnessTarget,
    LoudnormMeasurement,
    MixError,
    MixPlan,
    MusicBed,
    apply_filter,
    encode_arguments,
    input_arguments,
    measure_arguments,
    mix_filter_graph,
    music_transcode_arguments,
    parse_ebur128_summary,
    parse_loudnorm_report,
)

LOUDNORM_STDERR = """Input #0, wav, from 'x.wav':
[Parsed_loudnorm_0 @ 000001]
{
	"input_i" : "-23.41",
	"input_tp" : "-6.22",
	"input_lra" : "3.10",
	"input_thresh" : "-33.56",
	"output_i" : "-16.62",
	"output_tp" : "-1.50",
	"output_lra" : "2.40",
	"output_thresh" : "-26.80",
	"normalization_type" : "dynamic",
	"target_offset" : "0.62"
}
"""

EBUR_STDERR = """  Duration: 00:00:10.00, bitrate: 192 kb/s
[Parsed_ebur128_0 @ 0000] Summary:

  Integrated loudness:
    I:         -16.2 LUFS
    Threshold: -26.3 LUFS

  Loudness range:
    LRA:         4.1 LU
    Threshold: -36.3 LUFS
    LRA low:   -19.0 LUFS
    LRA high:  -14.9 LUFS

  True peak:
    Peak:       -1.3 dBFS
"""

SCENES = (Path("scene-0.wav"), Path("scene-1.wav"), Path("scene-2.wav"))


def voice_only() -> MixPlan:
    return MixPlan(scene_paths=SCENES, padding_ms=350, total_ms=12_500, tail_ms=1000)


def with_music() -> MixPlan:
    return MixPlan(scene_paths=SCENES, padding_ms=350, total_ms=12_500, tail_ms=1000, music=MusicBed(Path("bed.m4a")))


def test_voice_only_graph_pads_every_scene_but_the_last_and_the_whole_track() -> None:
    graph = mix_filter_graph(voice_only())

    assert graph.count("apad=pad_dur=0.350") == 2
    assert "[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=mono,apad=pad_dur=0.350[s0]" in graph
    assert "[2:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=mono[s2]" in graph
    assert "[s0][s1][s2]concat=n=3:v=0:a=1[cat]" in graph
    assert "apad=whole_dur=12.500,atrim=end=12.500" in graph
    assert graph.endswith("pan=stereo|c0=c0|c1=c0[mix]")
    assert "sidechaincompress" not in graph


def test_single_scene_graph_skips_concat() -> None:
    plan = MixPlan(scene_paths=(Path("a.wav"),), padding_ms=350, total_ms=2000, tail_ms=1000)

    graph = mix_filter_graph(plan)

    assert "concat" not in graph
    assert "apad=pad_dur" not in graph
    assert "[s0]anull[cat]" in graph


def test_zero_padding_adds_no_per_scene_padding() -> None:
    plan = MixPlan(scene_paths=SCENES, padding_ms=0, total_ms=5000, tail_ms=0)

    assert "pad_dur" not in mix_filter_graph(plan)


def test_music_graph_loops_trims_lowers_fades_and_ducks_under_the_voice() -> None:
    graph = mix_filter_graph(with_music())

    assert "[3:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo" in graph
    assert "atrim=end=12.500" in graph
    assert "volume=-18.0dB" in graph
    assert "afade=t=in:st=0:d=1.000" in graph
    assert "afade=t=out:st=11.500:d=1.000" in graph
    assert "asplit=2[vo][key]" in graph
    assert "[bed][key]sidechaincompress=threshold=0.02:ratio=8.0:attack=15.0:release=350.0:makeup=1[ducked]" in graph
    assert graph.endswith("[vo][ducked]amix=inputs=2:duration=first:normalize=0:dropout_transition=0[mix]")


def test_music_without_tail_has_no_fade_out() -> None:
    plan = MixPlan(scene_paths=SCENES, padding_ms=350, total_ms=9000, tail_ms=0, music=MusicBed(Path("bed.m4a")))

    assert "afade=t=out" not in mix_filter_graph(plan)


def test_music_settings_flow_into_the_graph() -> None:
    plan = MixPlan(
        scene_paths=SCENES,
        padding_ms=350,
        total_ms=9000,
        tail_ms=1000,
        music=MusicBed(Path("bed.m4a"), gain_db=-22.5, fade_in_ms=2000, ducking=DuckingSettings(0.05, 4.0, 5.0, 200.0)),
    )

    graph = mix_filter_graph(plan)

    assert "volume=-22.5dB" in graph
    assert "afade=t=in:st=0:d=2.000" in graph
    assert "threshold=0.05:ratio=4.0:attack=5.0:release=200.0" in graph


def test_inputs_put_scenes_first_and_loop_the_music() -> None:
    arguments = input_arguments(with_music())

    assert arguments[:4] == ["-protocol_whitelist", "file", "-i", "scene-0.wav"]
    music_start = arguments.index("-stream_loop")
    assert arguments[music_start : music_start + 3] == ["-stream_loop", "-1", "-protocol_whitelist"]
    assert arguments[-1] == "bed.m4a"
    assert arguments.count("-i") == 4


def test_pass_one_measures_without_changing_the_audio() -> None:
    arguments = measure_arguments(voice_only())

    graph = arguments[arguments.index("-filter_complex") + 1]
    assert graph.endswith("[mix]loudnorm=I=-16.0:TP=-1.5:LRA=11.0:print_format=json[out]")
    assert arguments[-3:] == ["-f", "null", "-"]


def test_pass_two_applies_the_measured_values_linearly_and_encodes_aac() -> None:
    measurement = LoudnormMeasurement(-23.41, -6.22, 3.1, -33.56, 0.62)

    arguments = encode_arguments(voice_only(), measurement, Path("out.m4a"))

    graph = arguments[arguments.index("-filter_complex") + 1]
    assert (
        "[mix]loudnorm=I=-16.0:TP=-1.5:LRA=11.0:measured_I=-23.41:measured_TP=-6.22:measured_LRA=3.10"
        ":measured_thresh=-33.56:offset=0.62:linear=true:print_format=summary,aresample=48000[out]"
    ) in graph
    assert arguments[arguments.index("-c:a") + 1] == "aac"
    assert arguments[arguments.index("-b:a") + 1] == "192k"
    assert arguments[arguments.index("-ar") + 1] == "48000"
    assert arguments[arguments.index("-ac") + 1] == "2"
    assert arguments[-1] == "out.m4a"


def test_custom_target_is_used_in_both_passes() -> None:
    plan = MixPlan(scene_paths=SCENES, padding_ms=0, total_ms=5000, tail_ms=0, target=LoudnessTarget(-14.0, -1.0, 9.0))

    assert "I=-14.0:TP=-1.0:LRA=9.0" in measure_arguments(plan)[measure_arguments(plan).index("-filter_complex") + 1]
    assert "I=-14.0:TP=-1.0:LRA=9.0" in apply_filter(plan.target, LoudnormMeasurement(-20, -5, 3, -30, 0))


def test_silent_measurement_skips_loudnorm() -> None:
    silent = LoudnormMeasurement(float("-inf"), float("-inf"), 0.0, float("-inf"), 0.0)

    assert not silent.is_measurable
    assert apply_filter(LoudnessTarget(), silent) == "[mix]aresample=48000[out]"
    assert apply_filter(LoudnessTarget(), None) == "[mix]aresample=48000[out]"


@pytest.mark.parametrize(
    "plan",
    [
        MixPlan(scene_paths=(), padding_ms=0, total_ms=1000, tail_ms=0),
        MixPlan(scene_paths=SCENES, padding_ms=0, total_ms=0, tail_ms=0),
        MixPlan(scene_paths=SCENES, padding_ms=-1, total_ms=1000, tail_ms=0),
        MixPlan(scene_paths=SCENES, padding_ms=0, total_ms=1000, tail_ms=-5),
    ],
)
def test_invalid_plans_are_refused(plan: MixPlan) -> None:
    with pytest.raises(MixError):
        mix_filter_graph(plan)


def test_loudnorm_report_is_read_from_stderr_noise() -> None:
    measurement = parse_loudnorm_report(LOUDNORM_STDERR)

    assert measurement == LoudnormMeasurement(-23.41, -6.22, 3.1, -33.56, 0.62)
    assert measurement.is_measurable


def test_loudnorm_report_with_infinite_values_is_not_measurable() -> None:
    stderr = (
        '{"input_i": "-inf", "input_tp": "-inf", "input_lra": "0.00", "input_thresh": "-70.00", "target_offset": "inf"}'
    )

    assert not parse_loudnorm_report(stderr).is_measurable


@pytest.mark.parametrize("stderr", ["", "no json here", '{"input_i": "oops"}', '{"other": 1}'])
def test_missing_loudnorm_report_is_an_error(stderr: str) -> None:
    with pytest.raises(MixError):
        parse_loudnorm_report(stderr)


def test_ebur128_summary_is_parsed() -> None:
    report = parse_ebur128_summary(EBUR_STDERR)

    assert (report.integrated_lufs, report.true_peak_dbtp, report.loudness_range) == (-16.2, -1.3, 4.1)


def test_ebur128_summary_without_peak_is_an_error() -> None:
    with pytest.raises(MixError):
        parse_ebur128_summary("Summary:\n I: -16.0 LUFS\n LRA: 4.0 LU\n")


def test_music_transcode_targets_aac_stereo_48k_256k() -> None:
    arguments = music_transcode_arguments(Path("bed.m4a"))

    assert arguments[arguments.index("-c:a") + 1] == "aac"
    assert arguments[arguments.index("-b:a") + 1] == "256k"
    assert arguments[arguments.index("-ar") + 1] == "48000"
    assert arguments[arguments.index("-ac") + 1] == "2"
    assert "-vn" in arguments
    assert arguments[-1] == "bed.m4a"
