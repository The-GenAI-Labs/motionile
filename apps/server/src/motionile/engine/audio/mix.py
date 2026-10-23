import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from motionile.engine.audio.sources import ALLOWED_DEMUXERS, file_input, staged_source
from motionile.engine.ffmpeg import FfmpegError, FfmpegTools, run_ffmpeg, run_process

SAMPLE_RATE = 48_000
MS_PER_SECOND = 1000
MIX_TIMEOUT_SECONDS = 600.0
MEASURE_TIMEOUT_SECONDS = 300.0
TRANSCODE_TIMEOUT_SECONDS = 300.0
MIX_BITRATE = "192k"
MUSIC_BITRATE = "256k"
JSON_OBJECT_PATTERN = re.compile(r"\{[^{}]*\}")
SUMMARY_INTEGRATED = re.compile(r"I:\s+(-?inf|-?\d+(?:\.\d+)?)\s+LUFS")
SUMMARY_RANGE = re.compile(r"LRA:\s+(-?inf|-?\d+(?:\.\d+)?)\s+LU")
SUMMARY_PEAK = re.compile(r"Peak:\s+(-?inf|-?\d+(?:\.\d+)?)\s+dBFS")


@dataclass(frozen=True, slots=True)
class DuckingSettings:
    threshold: float = 0.02
    ratio: float = 8.0
    attack_ms: float = 15.0
    release_ms: float = 350.0


@dataclass(frozen=True, slots=True)
class MusicBed:
    path: Path
    gain_db: float = -18.0
    fade_in_ms: int = 1000
    ducking: DuckingSettings = field(default_factory=DuckingSettings)


@dataclass(frozen=True, slots=True)
class LoudnessTarget:
    integrated_lufs: float = -16.0
    true_peak_dbtp: float = -1.5
    loudness_range: float = 11.0


@dataclass(frozen=True, slots=True)
class MixPlan:
    scene_paths: tuple[Path, ...]
    padding_ms: int
    total_ms: int
    tail_ms: int
    music: MusicBed | None = None
    target: LoudnessTarget = field(default_factory=LoudnessTarget)


@dataclass(frozen=True, slots=True)
class LoudnormMeasurement:
    input_i: float
    input_tp: float
    input_lra: float
    input_thresh: float
    target_offset: float

    @property
    def is_measurable(self) -> bool:
        return all(math.isfinite(value) for value in (self.input_i, self.input_tp, self.input_lra, self.input_thresh))


@dataclass(frozen=True, slots=True)
class MixResult:
    path: Path
    measurement: LoudnormMeasurement
    normalized: bool


@dataclass(frozen=True, slots=True)
class LoudnessReport:
    integrated_lufs: float
    true_peak_dbtp: float
    loudness_range: float


class MixError(ValueError):
    pass


def seconds(milliseconds: int) -> str:
    return f"{milliseconds / MS_PER_SECOND:.3f}"


def voice_chains(scene_count: int, padding_ms: int, total_ms: int, final_label: str) -> list[str]:
    chains: list[str] = []
    for index in range(scene_count):
        padding = f",apad=pad_dur={seconds(padding_ms)}" if index < scene_count - 1 and padding_ms > 0 else ""
        chains.append(
            f"[{index}:a]aresample={SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=mono{padding}[s{index}]"
        )
    labels = "".join(f"[s{index}]" for index in range(scene_count))
    joined = "anull" if scene_count == 1 else f"concat=n={scene_count}:v=0:a=1"
    chains.append(f"{labels}{joined}[cat]")
    chains.append(
        f"[cat]apad=whole_dur={seconds(total_ms)},atrim=end={seconds(total_ms)},asetpts=N/SR/TB,"
        f"pan=stereo|c0=c0|c1=c0{final_label}"
    )
    return chains


def music_chain(music: MusicBed, input_index: int, total_ms: int, tail_ms: int) -> str:
    chain = (
        f"[{input_index}:a]aresample={SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"atrim=end={seconds(total_ms)},asetpts=N/SR/TB,volume={music.gain_db:.1f}dB,"
        f"afade=t=in:st=0:d={seconds(music.fade_in_ms)}"
    )
    if tail_ms > 0:
        fade_ms = min(tail_ms, total_ms)
        chain += f",afade=t=out:st={seconds(total_ms - fade_ms)}:d={seconds(fade_ms)}"
    return chain + "[bed]"


def ducking_chain(ducking: DuckingSettings) -> str:
    return (
        f"[bed][key]sidechaincompress=threshold={ducking.threshold}:ratio={ducking.ratio}"
        f":attack={ducking.attack_ms}:release={ducking.release_ms}:makeup=1[ducked]"
    )


def mix_filter_graph(plan: MixPlan) -> str:
    scene_count = len(plan.scene_paths)
    if scene_count == 0:
        raise MixError("a mix needs at least one scene")
    if plan.total_ms <= 0 or plan.padding_ms < 0 or plan.tail_ms < 0:
        raise MixError("the mix durations are out of range")
    if plan.music is None:
        return ";".join(voice_chains(scene_count, plan.padding_ms, plan.total_ms, "[mix]"))
    chains = voice_chains(scene_count, plan.padding_ms, plan.total_ms, ",asplit=2[vo][key]")
    chains.append(music_chain(plan.music, scene_count, plan.total_ms, plan.tail_ms))
    chains.append(ducking_chain(plan.music.ducking))
    chains.append("[vo][ducked]amix=inputs=2:duration=first:normalize=0:dropout_transition=0[mix]")
    return ";".join(chains)


def loudnorm_target(target: LoudnessTarget) -> str:
    return f"loudnorm=I={target.integrated_lufs}:TP={target.true_peak_dbtp}:LRA={target.loudness_range}"


def measure_filter(target: LoudnessTarget) -> str:
    return f"[mix]{loudnorm_target(target)}:print_format=json[out]"


def apply_filter(target: LoudnessTarget, measurement: LoudnormMeasurement | None) -> str:
    if measurement is None or not measurement.is_measurable:
        return f"[mix]aresample={SAMPLE_RATE}[out]"
    return (
        f"[mix]{loudnorm_target(target)}"
        f":measured_I={measurement.input_i:.2f}:measured_TP={measurement.input_tp:.2f}"
        f":measured_LRA={measurement.input_lra:.2f}:measured_thresh={measurement.input_thresh:.2f}"
        f":offset={measurement.target_offset:.2f}:linear=true:print_format=summary,aresample={SAMPLE_RATE}[out]"
    )


def input_arguments(plan: MixPlan) -> list[str]:
    arguments: list[str] = []
    for path in plan.scene_paths:
        arguments.extend(file_input(path))
    if plan.music is not None:
        arguments.extend(["-stream_loop", "-1", *file_input(plan.music.path)])
    return arguments


def measure_arguments(plan: MixPlan) -> list[str]:
    graph = f"{mix_filter_graph(plan)};{measure_filter(plan.target)}"
    return [*input_arguments(plan), "-filter_complex", graph, "-map", "[out]", "-f", "null", "-"]


def encode_arguments(plan: MixPlan, measurement: LoudnormMeasurement | None, destination: Path) -> list[str]:
    graph = f"{mix_filter_graph(plan)};{apply_filter(plan.target, measurement)}"
    return [
        *input_arguments(plan),
        "-filter_complex",
        graph,
        "-map",
        "[out]",
        "-map_metadata",
        "-1",
        "-c:a",
        "aac",
        "-b:a",
        MIX_BITRATE,
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        "-y",
        str(destination),
    ]


def parse_loudnorm_report(stderr: str) -> LoudnormMeasurement:
    for candidate in reversed(JSON_OBJECT_PATTERN.findall(stderr)):
        if "input_i" not in candidate:
            continue
        try:
            document = json.loads(candidate)
            return LoudnormMeasurement(
                input_i=float(document["input_i"]),
                input_tp=float(document["input_tp"]),
                input_lra=float(document["input_lra"]),
                input_thresh=float(document["input_thresh"]),
                target_offset=float(document["target_offset"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
    raise MixError("the loudness measurement could not be read")


def parse_ebur128_summary(stderr: str) -> LoudnessReport:
    summary = stderr[stderr.rfind("Summary:") :] if "Summary:" in stderr else stderr
    integrated = SUMMARY_INTEGRATED.search(summary)
    loudness_range = SUMMARY_RANGE.search(summary)
    peak = SUMMARY_PEAK.search(summary)
    if integrated is None or loudness_range is None or peak is None:
        raise MixError("the loudness summary could not be read")
    return LoudnessReport(float(integrated.group(1)), float(peak.group(1)), float(loudness_range.group(1)))


async def run_with_report(tools: FfmpegTools, arguments: Sequence[str], *, timeout_seconds: float) -> str:
    command = [tools.ffmpeg, "-hide_banner", "-nostdin", "-nostats", "-loglevel", "info", *arguments]
    result = await run_process(command, timeout_seconds=timeout_seconds)
    if result.returncode != 0:
        raise FfmpegError(
            f"ffmpeg exited with status {result.returncode}", stderr=result.stderr, returncode=result.returncode
        )
    return result.stderr


async def mix_audio(
    tools: FfmpegTools, plan: MixPlan, destination: Path, *, timeout_seconds: float = MIX_TIMEOUT_SECONDS
) -> MixResult:
    report = await run_with_report(tools, measure_arguments(plan), timeout_seconds=timeout_seconds)
    measurement = parse_loudnorm_report(report)
    await run_ffmpeg(tools, encode_arguments(plan, measurement, destination), timeout_seconds=timeout_seconds)
    return MixResult(destination, measurement, normalized=measurement.is_measurable)


async def measure_loudness(
    tools: FfmpegTools, path: Path, *, timeout_seconds: float = MEASURE_TIMEOUT_SECONDS
) -> LoudnessReport:
    arguments = [*file_input(path), "-af", "ebur128=peak=true:framelog=quiet", "-f", "null", "-"]
    return parse_ebur128_summary(await run_with_report(tools, arguments, timeout_seconds=timeout_seconds))


def music_transcode_arguments(destination: Path) -> list[str]:
    return [
        "-vn",
        "-map",
        "0:a:0",
        "-map_metadata",
        "-1",
        "-ac",
        "2",
        "-ar",
        str(SAMPLE_RATE),
        "-c:a",
        "aac",
        "-b:a",
        MUSIC_BITRATE,
        "-movflags",
        "+faststart",
        "-y",
        str(destination),
    ]


async def transcode_music(
    tools: FfmpegTools,
    source: bytes | Path,
    destination: Path,
    *,
    timeout_seconds: float = TRANSCODE_TIMEOUT_SECONDS,
) -> Path:
    async with staged_source(source, formats=ALLOWED_DEMUXERS) as resolved:
        await run_ffmpeg(
            tools,
            [*resolved.arguments, *music_transcode_arguments(destination)],
            timeout_seconds=timeout_seconds,
            stdin=resolved.stdin,
        )
    return destination
