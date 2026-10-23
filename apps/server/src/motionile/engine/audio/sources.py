import asyncio
import shutil
import tempfile
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from motionile.engine.ffmpeg import PIPE_PROTOCOLS

ALLOWED_DEMUXERS = "wav,mp3,ogg,flac,mov,matroska,aac"
FILE_ONLY_PROTOCOLS = "file"
ISO_BMFF_BRAND_OFFSET = 4
ISO_BMFF_BRAND = b"ftyp"
STAGED_NAME = "input.bin"


@dataclass(frozen=True, slots=True)
class AudioSource:
    arguments: tuple[str, ...]
    stdin: bytes | None


def format_restriction(formats: str | None) -> tuple[str, ...]:
    return ("-format_whitelist", formats) if formats else ()


def file_input(path: Path, formats: str | None = None) -> tuple[str, ...]:
    return (*format_restriction(formats), "-protocol_whitelist", FILE_ONLY_PROTOCOLS, "-i", str(path))


def pipe_input(formats: str | None = None) -> tuple[str, ...]:
    return (*format_restriction(formats), "-protocol_whitelist", PIPE_PROTOCOLS, "-i", "pipe:0")


def needs_seekable_input(data: bytes) -> bool:
    return data[ISO_BMFF_BRAND_OFFSET : ISO_BMFF_BRAND_OFFSET + len(ISO_BMFF_BRAND)] == ISO_BMFF_BRAND


@asynccontextmanager
async def staged_source(source: bytes | Path, *, formats: str | None = None) -> AsyncGenerator[AudioSource]:
    if isinstance(source, Path):
        yield AudioSource(file_input(source, formats), None)
        return
    if not needs_seekable_input(source):
        yield AudioSource(pipe_input(formats), source)
        return
    directory = await asyncio.to_thread(tempfile.mkdtemp, prefix="motionile-audio-")
    try:
        staged = Path(directory) / STAGED_NAME
        await asyncio.to_thread(staged.write_bytes, source)
        yield AudioSource(file_input(staged, formats), None)
    finally:
        await asyncio.to_thread(shutil.rmtree, directory, ignore_errors=True)
