import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from playwright.async_api import Browser

from motionile.engine.render.models import RenderEngineConfig
from motionile.engine.render.reaper import (
    ListedProcess,
    SystemProcessReaper,
    marked_tree,
    parse_listing,
)
from motionile.engine.render.sandbox import RenderSandbox

LISTING = """
    1     0 /sbin/init
  100     1 python worker
  200   100 chrome --headless --motionile-render-id=abc --type=browser
  201   200 chrome --type=renderer
  202   201 chrome --type=utility
  300     1 chrome --headless --motionile-render-id=other
  400   100 grep --motionile-render-id=abcd
"""


def test_the_listing_is_parsed_into_pids_parents_and_commands() -> None:
    processes = parse_listing(LISTING)

    assert ListedProcess(200, 100, "chrome --headless --motionile-render-id=abc --type=browser") in processes
    assert len(processes) == 7
    assert parse_listing("garbage\nPID PPID ARGS\n") == []


def test_only_the_marked_processes_and_their_descendants_are_selected() -> None:
    selected = marked_tree(parse_listing(LISTING), "abc", own_pid=100)

    assert selected == [202, 201, 200]


def test_the_current_process_is_never_selected() -> None:
    listing = "  50     1 python --motionile-render-id=abc\n  51    50 chrome\n"

    assert marked_tree(parse_listing(listing), "abc", own_pid=50) == []


@dataclass
class Recorder:
    commands: list[Sequence[str]] = field(default_factory=list[Sequence[str]])
    killed: list[int] = field(default_factory=list[int])

    async def run(self, command: Sequence[str]) -> str:
        self.commands.append(command)
        return LISTING

    async def kill(self, pid: int) -> None:
        self.killed.append(pid)


async def test_the_reaper_kills_descendants_before_their_parents() -> None:
    recorder = Recorder()

    reaped = await SystemProcessReaper(recorder.run, recorder.kill).reap("abc")

    assert reaped == recorder.killed == [202, 201, 200]
    assert len(recorder.commands) == 1


class HangingBrowser:
    def __init__(self) -> None:
        self.closing = asyncio.Event()

    async def close(self) -> None:
        await self.closing.wait()


class RecordingReaper:
    def __init__(self) -> None:
        self.markers: list[str] = []

    async def reap(self, marker: str) -> list[int]:
        self.markers.append(marker)
        return []


async def test_a_browser_that_does_not_close_in_time_is_reaped_by_its_marker() -> None:
    reaper = RecordingReaper()
    sandbox = RenderSandbox(
        RenderEngineConfig(parallel_pages=1, shutdown_timeout_seconds=0.05), process_marker="marker-9", reaper=reaper
    )
    cast("Any", sandbox)._browser = cast("Browser", HangingBrowser())

    await sandbox.close()

    assert reaper.markers == ["marker-9"]


class ClosingBrowser:
    async def close(self) -> None:
        return None


async def test_a_browser_that_closes_cleanly_is_not_reaped() -> None:
    reaper = RecordingReaper()
    sandbox = RenderSandbox(RenderEngineConfig(parallel_pages=1), process_marker="marker-1", reaper=reaper)
    cast("Any", sandbox)._browser = cast("Browser", ClosingBrowser())

    await sandbox.close()

    assert reaper.markers == []
