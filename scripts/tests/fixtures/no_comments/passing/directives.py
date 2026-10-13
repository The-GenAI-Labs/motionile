#!/usr/bin/env python3
import subprocess

COLOR = "#0E0E10"
URL = "https://example.com/page#section"
TEMPLATE = """
# not a comment because this is a string
"""


def run() -> None:
    subprocess.run(["ls"], check=True)  # noqa: S603, S607
    value: int = "text"  # type: ignore[assignment]
    if value:  # pragma: no cover
        raise SystemExit(value)  # type: ignore[arg-type]  # noqa: TRY003
