import asyncio
import os
import signal
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

PROCESS_MARKER_FLAG = "--motionile-render-id"
WINDOWS_LISTING = (
    'Get-CimInstance Win32_Process | ForEach-Object { "$($_.ProcessId) $($_.ParentProcessId) $($_.CommandLine)" }'
)

type CommandRunner = Callable[[Sequence[str]], Awaitable[str]]
type ProcessKiller = Callable[[int], Awaitable[None]]


class ProcessReaper(Protocol):
    async def reap(self, marker: str) -> list[int]: ...


@dataclass(frozen=True, slots=True)
class ListedProcess:
    pid: int
    parent_pid: int
    command: str


def parse_listing(listing: str) -> list[ListedProcess]:
    processes: list[ListedProcess] = []
    for line in listing.splitlines():
        pid, _, rest = line.strip().partition(" ")
        parent, _, command = rest.strip().partition(" ")
        if pid.isdigit() and parent.isdigit():
            processes.append(ListedProcess(int(pid), int(parent), command.strip()))
    return processes


def marked_tree(processes: Sequence[ListedProcess], marker: str, own_pid: int) -> list[int]:
    flag = f"{PROCESS_MARKER_FLAG}={marker}"
    selected = {process.pid for process in processes if process.pid != own_pid and flag in process.command.split()}
    grown = True
    while grown:
        children = {
            process.pid
            for process in processes
            if process.parent_pid in selected and process.pid not in selected and process.pid != own_pid
        }
        grown = bool(children)
        selected |= children
    return sorted(selected, reverse=True)


async def run_command(command: Sequence[str]) -> str:
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    stdout, _ = await process.communicate()
    return stdout.decode(errors="replace")


async def kill_process(pid: int) -> None:
    if sys.platform == "win32":
        await run_command(["taskkill", "/PID", str(pid), "/F"])
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return


class SystemProcessReaper:
    def __init__(self, run: CommandRunner = run_command, kill: ProcessKiller = kill_process) -> None:
        self._run = run
        self._kill = kill

    async def reap(self, marker: str) -> list[int]:
        command = (
            ["powershell", "-NoProfile", "-Command", WINDOWS_LISTING]
            if sys.platform == "win32"
            else ["ps", "-eo", "pid=,ppid=,args="]
        )
        pids = marked_tree(parse_listing(await self._run(command)), marker, os.getpid())
        for pid in pids:
            await self._kill(pid)
        return pids
