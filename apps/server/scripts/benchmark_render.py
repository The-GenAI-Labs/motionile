import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from html import escape
from pathlib import Path

from motionile.engine.ffmpeg import FfmpegTools
from motionile.engine.render.capture import CaptureRequest
from motionile.engine.render.models import Aspect, RenderEngineConfig
from motionile.engine.render.pipeline import AspectJob, render_aspect
from motionile.engine.render.sandbox import RenderSandbox
from motionile.engine.render.sanitize import sanitize_composition
from motionile.engine.render.synthetic import SyntheticScene, build_synthetic_narration, synthesize_tone

TARGET_SECONDS_PER_VIDEO_MINUTE = 180.0
SEED = 20261019
WORDS = (
    "motion",
    "frames",
    "narration",
    "timeline",
    "browser",
    "capture",
    "encoder",
    "segments",
    "pipeline",
    "voice",
    "picture",
    "render",
)
WORDS_PER_SCENE = 12

STYLE = """
.title { margin: 0; font-size: calc(var(--mo-text-title) * 1.1); font-weight: 800; line-height: 1.15;
  letter-spacing: -0.03em; text-align: center; }
.word { display: inline-block; margin-inline: 0.14em; }
.bars { display: flex; gap: calc(var(--mo-unit) * 2); align-items: flex-end; height: calc(var(--mo-unit) * 16);
  margin-top: calc(var(--mo-unit) * 5); }
.bar { width: calc(var(--mo-unit) * 6); height: 100%; border-radius: calc(var(--mo-unit)) calc(var(--mo-unit)) 0 0;
  background: var(--mo-accent); transform-origin: bottom center; }
.ring { width: calc(var(--mo-unit) * 9); height: calc(var(--mo-unit) * 9); margin-top: calc(var(--mo-unit) * 4);
  border: calc(var(--mo-unit) * 0.6) solid var(--mo-accent); border-radius: 999px;
  animation: breathe 2s ease-in-out infinite; }
@keyframes breathe { from { transform: scale(0.7); } to { transform: scale(1.1); } }
"""

SCRIPT = """
const WORD_SECONDS = 0.3;
const LEVELS = [0.4, 0.8, 0.55, 1, 0.65];
const build = (ctx) => {
  const title = ctx.root.querySelector(".title");
  ctx.words.forEach((word, index) => {
    const node = document.createElement("span");
    node.className = "word";
    node.textContent = word.text;
    title.append(node);
    ctx.timeline.from(node, { opacity: 0, y: 36, duration: WORD_SECONDS, ease: "power3.out" },
      Math.min(ctx.at(index), ctx.duration - WORD_SECONDS));
  });
  ctx.root.querySelectorAll(".bar").forEach((bar, index) => {
    ctx.timeline.from(bar, { scaleY: 0.05, duration: 0.5, ease: "power2.out" },
      Math.min(0.2 + index * 0.15, ctx.duration - 0.5));
    ctx.timeline.to(bar, { scaleY: LEVELS[index], duration: 0.4 }, Math.min(1.2 + index * 0.1, ctx.duration - 0.4));
  });
};
const ids = Array.from(document.querySelectorAll("[data-scene]")).map((element) => element.dataset.scene);
Motionile.composition({
  aspects: ["16:9", "9:16", "1:1"],
  scenes: ids.map((id) => ({ id, build })),
});
"""


@dataclass(frozen=True)
class AspectMeasurement:
    aspect: str
    frames: int
    video_seconds: float
    wall_seconds: float
    seconds_per_video_minute: float
    frames_per_second: float
    peak_parallelism: int


def scene_text(index: int) -> str:
    return " ".join(WORDS[(index * 5 + offset) % len(WORDS)] for offset in range(WORDS_PER_SCENE))


def build_scenes(duration_seconds: float) -> list[SyntheticScene]:
    scenes: list[SyntheticScene] = []
    while True:
        scenes.append(SyntheticScene(f"scene-{len(scenes) + 1}", scene_text(len(scenes))))
        if build_synthetic_narration(scenes).total_duration_ms >= duration_seconds * 1000:
            return scenes


def build_html(scenes: Sequence[SyntheticScene]) -> str:
    sections = "\n".join(
        f'      <section class="mo-scene mo-center" data-scene="{escape(scene.scene_id)}">\n'
        '        <h1 class="title"></h1>\n'
        '        <div class="bars"><div class="bar"></div><div class="bar"></div><div class="bar"></div>'
        '<div class="bar"></div><div class="bar"></div></div>\n'
        '        <div class="ring"></div>\n'
        "      </section>"
        for scene in scenes
    )
    return (
        '<!doctype html>\n<html lang="en">\n  <head>\n    <meta charset="utf-8" />\n'
        "    <title>Benchmark</title>\n"
        '    <link rel="stylesheet" href="https://runtime.motionile.local/v1/base.css" />\n'
        f"    <style>{STYLE}</style>\n"
        '    <script src="https://runtime.motionile.local/v1/gsap/gsap.min.js"></script>\n'
        '    <script src="https://runtime.motionile.local/v1/motionile.js"></script>\n'
        f'  </head>\n  <body>\n    <main class="mo-stage">\n{sections}\n    </main>\n'
        f"    <script>{SCRIPT}</script>\n  </body>\n</html>\n"
    )


async def measure(sandbox: RenderSandbox, config: RenderEngineConfig, job: AspectJob) -> AspectMeasurement:
    started = time.perf_counter()
    output = await render_aspect(sandbox, job, config)
    wall = time.perf_counter() - started
    frames = output.capture.total_frames
    video_seconds = frames / config.fps
    return AspectMeasurement(
        aspect=job.request.aspect.value,
        frames=frames,
        video_seconds=round(video_seconds, 2),
        wall_seconds=round(wall, 2),
        seconds_per_video_minute=round(wall / (video_seconds / 60), 1),
        frames_per_second=round(frames / wall, 1),
        peak_parallelism=output.capture.peak_parallelism,
    )


def format_table(measurements: Sequence[AspectMeasurement], cpus: int) -> str:
    header = ("aspect", "frames", "wall s", "s per video min", "frames/s", "peak parallelism", "cpus")
    rows = [
        (
            item.aspect,
            str(item.frames),
            f"{item.wall_seconds:.1f}",
            f"{item.seconds_per_video_minute:.1f}",
            f"{item.frames_per_second:.1f}",
            str(item.peak_parallelism),
            str(cpus),
        )
        for item in measurements
    ]
    widths = [max(len(row[column]) for row in (header, *rows)) for column in range(len(header))]
    lines = ["  ".join(value.ljust(widths[column]) for column, value in enumerate(row)) for row in (header, *rows)]
    return "\n".join(lines)


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a synthetic composition end to end and report the speed.")
    parser.add_argument("--duration", type=float, default=60.0, help="Target narration length in seconds.")
    parser.add_argument("--aspects", nargs="+", default=[aspect.value for aspect in Aspect], choices=list(Aspect))
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--pages", type=int, default=None, help="Parallel capture pages; defaults to the CPU count.")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    return parser.parse_args(list(argv))


async def run(arguments: argparse.Namespace) -> int:
    scenes = build_scenes(arguments.duration)
    narration = build_synthetic_narration(scenes)
    html = sanitize_composition(build_html(scenes), scene_ids=[scene.scene_id for scene in scenes])
    html.raise_for_errors()
    cpus = os.cpu_count() or 1
    measurements: list[AspectMeasurement] = []
    with tempfile.TemporaryDirectory(prefix="motionile-bench-") as directory:
        work_directory = Path(directory)
        config = RenderEngineConfig(
            fps=arguments.fps,
            work_directory=work_directory,
            tools=FfmpegTools(ffmpeg=arguments.ffmpeg, ffprobe=arguments.ffprobe),
        )
        if arguments.pages is not None:
            config = replace(config, parallel_pages=arguments.pages)
        audio = await synthesize_tone(
            config.tools, work_directory / "audio.m4a", narration.total_duration_ms + config.tail_ms
        )
        async with RenderSandbox(config) as sandbox:
            for label in arguments.aspects:
                aspect = Aspect(label)
                request = CaptureRequest(html.html, narration, aspect, SEED)
                job = AspectJob(request, audio, work_directory / aspect.label)
                measurements.append(await measure(sandbox, config, job))
    sys.stdout.write(
        f"narration {narration.total_duration_ms / 1000:.1f} s, {len(scenes)} scenes, {arguments.fps} fps, "
        f"target {TARGET_SECONDS_PER_VIDEO_MINUTE:.0f} s per video minute\n"
    )
    sys.stdout.write(format_table(measurements, cpus) + "\n")
    sys.stdout.write(
        json.dumps(
            {
                "cpus": cpus,
                "narrationMs": narration.total_duration_ms,
                "fps": arguments.fps,
                "measurements": [asdict(item) for item in measurements],
            },
            indent=2,
        )
        + "\n"
    )
    within_budget = all(item.seconds_per_video_minute <= TARGET_SECONDS_PER_VIDEO_MINUTE for item in measurements)
    return 0 if within_budget else 1


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    return asyncio.run(run(arguments))


if __name__ == "__main__":
    sys.exit(main())
