import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from motionile.engine.render.capture import ChunkPlan, FramePage, HashFrameSink
from motionile.engine.render.models import Aspect
from motionile.engine.render.sandbox import PageSpec


def frame_bytes(frame_index: int) -> bytes:
    return f"frame-{frame_index}".encode()


@dataclass
class FakeFramePage:
    pages: "FakePageOpener"
    captured: list[int] = field(default_factory=list[int])
    closed: bool = False

    async def capture_frame(self, frame_index: int) -> bytes:
        await asyncio.sleep(0)
        if self.pages.fail_at == frame_index:
            raise self.pages.failure
        self.captured.append(frame_index)
        return frame_bytes(frame_index)

    async def close(self) -> None:
        self.closed = True


@dataclass
class FakePageOpener:
    fail_at: int | None = None
    failure: Exception = field(default_factory=lambda: RuntimeError("capture failed"))
    opened: list[FakeFramePage] = field(default_factory=list[FakeFramePage])
    specs: list[PageSpec] = field(default_factory=list[PageSpec])

    async def open_page(self, spec: PageSpec) -> FramePage:
        page = FakeFramePage(self)
        self.opened.append(page)
        self.specs.append(spec)
        return page


@dataclass
class RecordingSinks:
    sinks: dict[int, HashFrameSink] = field(default_factory=dict[int, HashFrameSink])
    paths: dict[int, Path | None] = field(default_factory=dict[int, Path | None])

    async def __call__(self, _aspect: Aspect, chunk: ChunkPlan) -> HashFrameSink:
        sink = HashFrameSink()
        self.sinks[chunk.index] = sink
        return sink

    def hashes_by_frame(self, plan: tuple[ChunkPlan, ...]) -> dict[int, str]:
        merged: dict[int, str] = {}
        for chunk in plan:
            sink = self.sinks.get(chunk.index)
            if sink is None:
                continue
            for offset, digest in enumerate(sink.hashes):
                merged[chunk.start_frame + offset] = digest
        return merged
