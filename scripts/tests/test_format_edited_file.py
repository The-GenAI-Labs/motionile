import json
from pathlib import Path

import pytest

from scripts.format_edited_file import edited_path, formatter_command, handle


def payload_for(path: Path) -> str:
    return json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(path)}})


@pytest.mark.parametrize(
    ("name", "tool"),
    [("module.py", "ruff"), ("page.tsx", "prettier"), ("config.mjs", "prettier"), ("ci.yml", "prettier")],
)
def test_picks_the_formatter_for_each_language(name: str, tool: str) -> None:
    command = formatter_command(Path(name))

    assert command is not None
    assert tool in command
    assert command[-1] == name


def test_skips_files_without_a_formatter() -> None:
    assert formatter_command(Path("Dockerfile")) is None


@pytest.mark.parametrize("payload", ["not json", "[]", '{"tool_input": "x"}', '{"tool_input": {"file_path": ""}}'])
def test_ignores_malformed_payloads(payload: str) -> None:
    assert edited_path(payload) is None


def test_runs_the_formatter_for_an_edited_file(tmp_path: Path) -> None:
    path = tmp_path / "module.py"
    path.write_text("VALUE=1\n", encoding="utf-8")
    calls: list[list[str]] = []

    def record(command: list[str]) -> int:
        calls.append(command)
        return 0

    assert handle(payload_for(path), record) == 0
    assert calls == [["uv", "run", "--project", "apps/server", "ruff", "format", str(path)]]


def test_never_blocks_when_formatting_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "page.tsx"
    path.write_text("export {};\n", encoding="utf-8")

    assert handle(payload_for(path), lambda _command: 1) == 0
    assert "Formatting" in capsys.readouterr().err


def test_ignores_missing_files(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def record(command: list[str]) -> int:
        calls.append(command)
        return 0

    assert handle(payload_for(tmp_path / "missing.py"), record) == 0
    assert calls == []
