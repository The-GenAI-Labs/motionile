import difflib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

REDACTED_LINE: Final = "[canary redacted]"
CONTEXT_LINES: Final = 3
CANARY_REFERENCE = re.compile(r"\{\{[^}]*\bcanary\b[^}]*\}\}|\{%[^%]*\bcanary\b[^%]*%\}")
HEADER_LINES: Final = 2


@dataclass(frozen=True, slots=True)
class BodyDiff:
    lines: list[str]
    added: int
    removed: int


def redacted_lines(body: str, canaries: Sequence[str]) -> list[str]:
    return [
        REDACTED_LINE if CANARY_REFERENCE.search(line) or any(canary in line for canary in canaries) else line
        for line in body.splitlines()
    ]


def diff_bodies(older: str, newer: str, canaries: Sequence[str], *, older_label: str, newer_label: str) -> BodyDiff:
    lines = list(
        difflib.unified_diff(
            redacted_lines(older, canaries),
            redacted_lines(newer, canaries),
            fromfile=older_label,
            tofile=newer_label,
            n=CONTEXT_LINES,
            lineterm="",
        )
    )
    body = lines[HEADER_LINES:]
    added = sum(1 for line in body if line.startswith("+"))
    removed = sum(1 for line in body if line.startswith("-"))
    return BodyDiff(lines, added, removed)
