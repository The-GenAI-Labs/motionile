import asyncio
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.ffmpeg import FfmpegTools, run_ffmpeg
from motionile.engine.render.models import RenderEngineConfig
from motionile.engine.render.synthetic import SyntheticScene, build_synthetic_narration

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
GOLDEN_ROOT = FIXTURES / "compositions"
MALICIOUS_ROOT = FIXTURES / "malicious"
GOLDEN_NAMES = (
    "kinetic-typography",
    "flow-diagram",
    "code-walkthrough",
    "data-structure",
    "comparison-split",
    "css-animation-scene",
    "responsive-scene",
)
PROBE_TIMEOUT_SECONDS = 20.0

TINY_COMPOSITION = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Determinism probe</title>
    <link rel="stylesheet" href="https://runtime.motionile.local/v1/base.css" />
    <style>
      .bar { height: 24px; margin-top: 18px; background: var(--mo-accent); border-radius: 12px; }
      .pulse { width: 120px; height: 120px; border-radius: 999px; background: var(--mo-surface);
        border: 6px solid var(--mo-accent); animation: grow 2s linear infinite; }
      .slide { transition: transform 1s linear 0.5s; }
      .slide[data-on] { transform: translateX(200px); }
      @keyframes grow { from { transform: scale(0.5); } to { transform: scale(1.2); } }
    </style>
    <script src="https://runtime.motionile.local/v1/gsap/gsap.min.js"></script>
    <script src="https://runtime.motionile.local/v1/motionile.js"></script>
  </head>
  <body>
    <main class="mo-stage">
      <section class="mo-scene mo-center" data-scene="one">
        <h1 class="mo-title" id="title">Frames stay identical</h1>
        <div class="pulse"></div>
        <div class="bar" id="bar"></div>
        <div class="slide mo-body" id="slide">slide</div>
      </section>
      <section class="mo-scene mo-center" data-scene="two">
        <h1 class="mo-title" id="second">Second scene</h1>
      </section>
    </main>
    <script>
      Motionile.composition({
        aspects: ["16:9", "9:16", "1:1"],
        scenes: [
          {
            id: "one",
            build(ctx) {
              document.getElementById("bar").style.width = `${200 + Math.floor(Math.random() * 400)}px`;
              ctx.timeline.from("#title", { opacity: 0, y: 40, duration: 0.5 }, 0.1);
              document.getElementById("slide").getBoundingClientRect();
              document.getElementById("slide").setAttribute("data-on", "");
            },
          },
          {
            id: "two",
            build(ctx) {
              ctx.timeline.from("#second", { opacity: 0, scale: 0.9, duration: 0.5 }, 0.2);
            },
          },
        ],
      });
    </script>
  </body>
</html>
"""
TINY_SCENES = (
    SyntheticScene("one", "Frames stay identical across runs"),
    SyntheticScene("two", "Second scene"),
)


@dataclass(frozen=True)
class Golden:
    name: str
    html: str
    scenes: tuple[SyntheticScene, ...]

    @property
    def scene_ids(self) -> list[str]:
        return [scene.scene_id for scene in self.scenes]

    def narration(self) -> NarrationDocument:
        return build_synthetic_narration(self.scenes)


def load_golden(name: str) -> Golden:
    directory = GOLDEN_ROOT / name
    document = json.loads((directory / "narration.json").read_text(encoding="utf-8"))
    scenes = tuple(SyntheticScene(item["sceneId"], item["text"]) for item in document["scenes"])
    return Golden(name=name, html=(directory / "composition.html").read_text(encoding="utf-8"), scenes=scenes)


def tiny_narration() -> NarrationDocument:
    return build_synthetic_narration(TINY_SCENES)


def runnable(command: str) -> bool:
    try:
        subprocess.run([command, "-version"], check=True, capture_output=True, timeout=PROBE_TIMEOUT_SECONDS)  # noqa: S603
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def resolve_tools() -> FfmpegTools | None:
    ffmpeg = os.environ.get("RENDER_FFMPEG_PATH") or shutil.which("ffmpeg") or "ffmpeg"
    ffprobe = os.environ.get("RENDER_FFPROBE_PATH") or shutil.which("ffprobe") or "ffprobe"
    if runnable(ffmpeg) and runnable(ffprobe):
        return FfmpegTools(ffmpeg=ffmpeg, ffprobe=ffprobe)
    return None


def render_config(tools: FfmpegTools, work_directory: Path, **overrides: Any) -> RenderEngineConfig:
    base = RenderEngineConfig(
        fps=15,
        chunk_seconds=2,
        parallel_pages=3,
        tail_ms=600,
        page_load_timeout_seconds=30,
        ready_timeout_seconds=30,
        frame_timeout_seconds=20,
        min_free_disk_mb=1,
        tools=tools,
        work_directory=work_directory,
    )
    return replace(base, **overrides)


async def frame_md5s(tools: FfmpegTools, video: Path) -> list[str]:
    result = await run_ffmpeg(
        tools,
        ["-i", str(video), "-an", "-f", "framemd5", "-"],
        timeout_seconds=300,
    )
    digests: list[str] = []
    for line in result.stdout.decode().splitlines():
        if line and not line.startswith("#"):
            digests.append(line.rsplit(",", 1)[-1].strip())
    return digests


async def process_lines() -> list[str]:
    if sys.platform == "win32":
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | Where-Object { $_.Name -notmatch 'powershell|pwsh' } "
            "| ForEach-Object { $_.CommandLine }",
        ]
    else:
        command = ["ps", "-eo", "args"]
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    stdout, _ = await process.communicate()
    return stdout.decode(errors="replace").splitlines()


async def leftover_processes(marker: str, *, wait_seconds: float = 10.0) -> list[str]:
    deadline = asyncio.get_running_loop().time() + wait_seconds
    found: list[str] = []
    while True:
        found = [line for line in await process_lines() if marker in line and "ps -eo" not in line]
        if not found or asyncio.get_running_loop().time() > deadline:
            return found
        await asyncio.sleep(0.5)


@dataclass
class Canary:
    hits: list[str] = field(default_factory=list[str])
    host: str = "127.0.0.1"
    tcp_port: int = 0
    udp_port: int = 0
    servers: list[asyncio.AbstractServer] = field(default_factory=list[asyncio.AbstractServer])
    transports: list[asyncio.DatagramTransport] = field(default_factory=list[asyncio.DatagramTransport])

    @property
    def authority(self) -> str:
        return f"{self.host}:{self.tcp_port}"

    @property
    def udp_authority(self) -> str:
        return f"{self.host}:{self.udp_port}"

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        with suppress(ConnectionError, asyncio.IncompleteReadError):
            line = await reader.readline()
            self.hits.append(f"tcp {line.decode(errors='replace').strip()}")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
            await writer.drain()
        writer.close()

    async def start(self) -> None:
        server = await asyncio.start_server(self.handle, self.host, 0)
        self.servers.append(server)
        self.tcp_port = server.sockets[0].getsockname()[1]
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(lambda: CanaryDatagrams(self), local_addr=(self.host, 0))
        self.transports.append(transport)
        self.udp_port = transport.get_extra_info("sockname")[1]

    async def stop(self) -> None:
        for server in self.servers:
            server.close()
            await server.wait_closed()
        for transport in self.transports:
            transport.close()

    def fill(self, html: str) -> str:
        return html.replace("__CANARY_UDP__", self.udp_authority).replace("__CANARY__", self.authority)


class CanaryDatagrams(asyncio.DatagramProtocol):
    def __init__(self, canary: Canary) -> None:
        self._canary = canary

    def datagram_received(self, data: bytes, addr: tuple[str | object, int]) -> None:
        self._canary.hits.append(f"udp {addr} {len(data)} bytes")


def unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))
