#!/usr/bin/env python3
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
PRETTIER_SUFFIXES = frozenset({".ts", ".tsx", ".js", ".mjs", ".cjs", ".json", ".md", ".yml", ".yaml", ".css"})

type Runner = Callable[[list[str]], int]


def formatter_command(path: Path) -> list[str] | None:
    if path.suffix == ".py":
        return ["uv", "run", "--project", "apps/server", "ruff", "format", str(path)]
    if path.suffix in PRETTIER_SUFFIXES:
        return ["pnpm", "exec", "prettier", "--write", "--ignore-unknown", str(path)]
    return None


def lookup(container: object, key: str) -> object:
    if not isinstance(container, dict):
        return None
    return cast("dict[str, object]", container).get(key)


def edited_path(payload: str) -> Path | None:
    try:
        event: object = json.loads(payload)
    except json.JSONDecodeError:
        return None
    file_path = lookup(lookup(event, "tool_input"), "file_path")
    return Path(file_path) if isinstance(file_path, str) and file_path else None


def run_in_repository(command: list[str]) -> int:
    return subprocess.run(command, cwd=REPOSITORY_ROOT, check=False).returncode  # noqa: S603


def handle(payload: str, run: Runner) -> int:
    path = edited_path(payload)
    if path is None or not path.is_file():
        return 0
    command = formatter_command(path)
    if command is None:
        return 0
    if run(command) != 0:
        sys.stderr.write(f"Formatting {path} failed.\n")
    return 0


if __name__ == "__main__":
    sys.exit(handle(sys.stdin.read(), run_in_repository))
