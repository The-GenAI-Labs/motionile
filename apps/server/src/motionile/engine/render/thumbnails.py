import asyncio
import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from motionile.engine.ffmpeg import FfmpegTools, run_ffmpeg
from motionile.engine.render.models import Aspect

FRAME_EXTRACT_TIMEOUT_SECONDS = 60.0
WEBP_QUALITY = 85
JPEG_QUALITY = 88
YUV_TO_RGB_FILTER = (
    "scale=in_color_matrix=bt709:in_range=tv:out_range=pc:flags=accurate_rnd+full_chroma_int,format=rgb24"
)


@dataclass(frozen=True)
class PosterFiles:
    webp: Path
    jpeg: Path


@dataclass(frozen=True)
class PosterBytes:
    webp: bytes
    jpeg: bytes


def clamp_poster_ms(poster_ms: int, duration_ms: int, frame_ms: int) -> int:
    return max(0, min(poster_ms, max(0, duration_ms - frame_ms)))


def encode_posters(png: bytes) -> PosterBytes:
    with Image.open(io.BytesIO(png)) as image:
        rgb = image.convert("RGB")
        webp = io.BytesIO()
        jpeg = io.BytesIO()
        rgb.save(webp, format="WEBP", quality=WEBP_QUALITY, method=4)
        rgb.save(jpeg, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return PosterBytes(webp=webp.getvalue(), jpeg=jpeg.getvalue())


async def extract_frame_png(tools: FfmpegTools, video: Path, time_ms: int) -> bytes:
    result = await run_ffmpeg(
        tools,
        [
            "-ss",
            f"{time_ms / 1000:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            YUV_TO_RGB_FILTER,
            "-f",
            "image2pipe",
            "-c:v",
            "png",
            "pipe:1",
        ],
        timeout_seconds=FRAME_EXTRACT_TIMEOUT_SECONDS,
    )
    return result.stdout


@dataclass(frozen=True)
class PosterTiming:
    poster_ms: int
    duration_ms: int
    fps: int


def make_directory(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)


async def write_posters(
    tools: FfmpegTools,
    video: Path,
    directory: Path,
    aspect: Aspect,
    timing: PosterTiming,
) -> PosterFiles:
    at_ms = clamp_poster_ms(timing.poster_ms, timing.duration_ms, round(1000 / timing.fps))
    png = await extract_frame_png(tools, video, at_ms)
    encoded = await asyncio.to_thread(encode_posters, png)
    await asyncio.to_thread(make_directory, directory)
    files = PosterFiles(webp=directory / f"poster-{aspect.label}.webp", jpeg=directory / f"poster-{aspect.label}.jpg")
    await asyncio.to_thread(files.webp.write_bytes, encoded.webp)
    await asyncio.to_thread(files.jpeg.write_bytes, encoded.jpeg)
    return files
