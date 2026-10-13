from pathlib import Path

import pytest

from scripts.check_module_boundaries import check_tree, main, resolve_relative

FIXTURES = Path(__file__).parent / "fixtures" / "module_boundaries"


def test_passing_fixture_has_no_violations() -> None:
    assert check_tree(FIXTURES / "passing") == []


def test_failing_fixture_reports_each_internal_import() -> None:
    violations = check_tree(FIXTURES / "failing")

    assert sorted((violation.line, violation.imported) for violation in violations) == [
        (1, "motionile.modules.billing.service"),
        (2, "motionile.modules.billing.repository"),
        (4, "motionile.modules.billing.repository"),
    ]
    assert all(violation.importer == "motionile.modules.credits.service" for violation in violations)


def test_violation_message_points_to_the_public_package() -> None:
    violation = check_tree(FIXTURES / "failing")[0]

    assert "import from motionile.modules.billing instead" in violation.describe(FIXTURES)


@pytest.mark.parametrize(
    ("importer", "is_package", "level", "target", "expected"),
    [
        (("a", "b", "c"), False, 1, "d", ("a", "b", "d")),
        (("a", "b", "c"), False, 2, "d.e", ("a", "d", "e")),
        (("a", "b"), True, 1, None, ("a", "b")),
    ],
)
def test_resolves_relative_imports(
    importer: tuple[str, ...], is_package: bool, level: int, target: str | None, expected: tuple[str, ...]
) -> None:
    assert resolve_relative(importer, is_package, level, target) == expected


def test_main_fails_on_violations(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--source-root", str(FIXTURES / "failing")]) == 1
    assert "3 module boundary violation(s) found." in capsys.readouterr().err


def test_main_passes_on_clean_tree() -> None:
    assert main(["--source-root", str(FIXTURES / "passing")]) == 0


def test_main_passes_on_real_code() -> None:
    assert main([]) == 0
