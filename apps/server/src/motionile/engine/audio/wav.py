import struct
from dataclasses import dataclass

RIFF_HEADER_BYTES = 12
CHUNK_HEADER_BYTES = 8
PCM_FORMAT_TAG = 1
BITS_PER_SAMPLE = 16
UNKNOWN_CHUNK_SIZE = 0xFFFFFFFF
FORMAT_CHUNK_MINIMUM_BYTES = 16
TEXT_CHUNK_ID = b"mtxt"


class WavError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class WavInfo:
    sample_rate: int
    channels: int
    frames: int
    data_offset: int
    data_bytes: int
    embedded_text: str | None

    @property
    def duration_ms(self) -> int:
        return round(self.frames * 1000 / self.sample_rate)


def chunk(chunk_id: bytes, payload: bytes) -> bytes:
    padding = b"\x00" if len(payload) % 2 else b""
    return chunk_id + struct.pack("<I", len(payload)) + payload + padding


def build_wav(pcm: bytes, *, sample_rate: int, channels: int = 1, embedded_text: str | None = None) -> bytes:
    block_align = channels * BITS_PER_SAMPLE // 8
    format_payload = struct.pack(
        "<HHIIHH", PCM_FORMAT_TAG, channels, sample_rate, sample_rate * block_align, block_align, BITS_PER_SAMPLE
    )
    body = b"WAVE" + chunk(b"fmt ", format_payload) + chunk(b"data", pcm)
    if embedded_text is not None:
        body += chunk(TEXT_CHUNK_ID, embedded_text.encode("utf-8"))
    return b"RIFF" + struct.pack("<I", len(body)) + body


def parse_wav(data: bytes) -> WavInfo:
    if len(data) < RIFF_HEADER_BYTES or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise WavError("not a RIFF/WAVE file")
    offset = RIFF_HEADER_BYTES
    sample_rate = channels = 0
    data_offset = data_bytes = -1
    embedded_text: str | None = None
    while offset + CHUNK_HEADER_BYTES <= len(data):
        chunk_id = data[offset : offset + 4]
        (size,) = struct.unpack("<I", data[offset + 4 : offset + CHUNK_HEADER_BYTES])
        body_start = offset + CHUNK_HEADER_BYTES
        available = len(data) - body_start
        if chunk_id == b"fmt " and size >= FORMAT_CHUNK_MINIMUM_BYTES and available >= size:
            _, channels, sample_rate, _, _, _ = struct.unpack("<HHIIHH", data[body_start : body_start + 16])
        elif chunk_id == b"data":
            data_offset = body_start
            data_bytes = available if size == UNKNOWN_CHUNK_SIZE or size > available else size
        elif chunk_id == TEXT_CHUNK_ID and available >= size:
            embedded_text = data[body_start : body_start + size].decode("utf-8", errors="replace")
        offset = body_start + size + (size % 2)
    if sample_rate <= 0 or channels <= 0 or data_offset < 0:
        raise WavError("missing fmt or data chunk")
    frames = data_bytes // (channels * BITS_PER_SAMPLE // 8)
    return WavInfo(sample_rate, channels, frames, data_offset, data_bytes, embedded_text)


def finalize_streamed_wav(data: bytes) -> bytes:
    info = parse_wav(data)
    patched = bytearray(data)
    patched[4:8] = struct.pack("<I", len(data) - CHUNK_HEADER_BYTES)
    size_offset = info.data_offset - 4
    patched[size_offset : size_offset + 4] = struct.pack("<I", info.data_bytes)
    return bytes(patched)
