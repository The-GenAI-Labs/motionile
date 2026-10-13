import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPOSITORY_ROOT / "apps" / "server"
FIXTURES = Path(__file__).parent / "fixtures" / "import_contracts"


def lint_imports(source_root: Path, cache_dir: Path) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("lint-imports")
    assert executable is not None
    environment = {**os.environ, "PYTHONPATH": str(source_root)}
    return subprocess.run(  # noqa: S603
        [executable, "--config", str(SERVER_ROOT / "pyproject.toml"), "--cache-dir", str(cache_dir)],
        cwd=source_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_contracts_pass_on_layered_fixture(tmp_path: Path) -> None:
    result = lint_imports(FIXTURES / "passing", tmp_path)

    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    ("fixture", "broken_contract"),
    [
        ("failing_core", "core imports nothing from modules, engine or mcp BROKEN"),
        ("failing_engine", "engine imports nothing from modules BROKEN"),
    ],
)
def test_contracts_fail_on_violating_fixture(tmp_path: Path, fixture: str, broken_contract: str) -> None:
    result = lint_imports(FIXTURES / fixture, tmp_path)

    assert result.returncode == 1
    assert broken_contract in result.stdout


def test_contracts_pass_on_real_code(tmp_path: Path) -> None:
    result = lint_imports(SERVER_ROOT / "src", tmp_path)

    assert result.returncode == 0, result.stdout
