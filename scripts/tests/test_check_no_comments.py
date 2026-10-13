from pathlib import Path

import pytest

from scripts import check_no_comments
from scripts.check_no_comments import check_file, collect_violations, is_python_directive, main, scanner_for

FIXTURES = Path(__file__).parent / "fixtures" / "no_comments"
PASSING = sorted(path for path in (FIXTURES / "passing").iterdir() if path.is_file())
FAILING = sorted(path for path in (FIXTURES / "failing").iterdir() if path.is_file())


@pytest.mark.parametrize("path", PASSING, ids=lambda path: path.name)
def test_passing_fixtures_have_no_violations(path: Path) -> None:
    assert scanner_for(path) is not None
    assert check_file(path) == []


@pytest.mark.parametrize("path", FAILING, ids=lambda path: path.name)
def test_failing_fixtures_are_reported(path: Path) -> None:
    violations = check_file(path)

    assert len(violations) == 1
    assert violations[0].path == path


@pytest.mark.parametrize(
    "comment",
    [
        "# noqa: S101",
        "# noqa: S603, S607",
        "# type: ignore[assignment]",
        "# type: ignore[arg-type]  # noqa: E501",
        "# pragma: no cover",
    ],
)
def test_accepts_python_directives(comment: str) -> None:
    assert is_python_directive(comment)


@pytest.mark.parametrize(
    "comment",
    ["# noqa", "# type: ignore", "# pragma: no branch", "# TODO: later", "# noqa: S101 because reasons", "#"],
)
def test_rejects_other_python_comments(comment: str) -> None:
    assert not is_python_directive(comment)


def test_ignores_files_without_a_comment_syntax(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_text("# Heading\n", encoding="utf-8")

    assert scanner_for(path) is None
    assert check_file(path) == []


def test_skips_excluded_directories(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    generated.mkdir()
    path = generated / "schema.py"
    path.write_text("# generated header\n", encoding="utf-8")

    assert collect_violations([path]) == []


def test_main_reports_violations_for_given_paths(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "module.py"
    path.write_text("VALUE = 1  # remark\n", encoding="utf-8")

    assert main([str(path)]) == 1
    assert "module.py:1: comment not allowed: # remark" in capsys.readouterr().err


def test_main_accepts_clean_paths(tmp_path: Path) -> None:
    path = tmp_path / "module.py"
    path.write_text("VALUE = 1\n", encoding="utf-8")

    assert main([str(path)]) == 0


def test_repository_has_no_comments() -> None:
    assert check_no_comments.main([]) == 0
