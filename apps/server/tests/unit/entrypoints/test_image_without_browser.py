import subprocess
import sys

import pytest

ENTRYPOINTS = [
    "import motionile.entrypoints.api",
    "import motionile.entrypoints.worker",
    "from motionile.core.tasks.app import load_task_modules; load_task_modules()",
    "import motionile.models",
]


@pytest.mark.parametrize("statement", ENTRYPOINTS)
def test_the_api_image_imports_without_the_browser_package(statement: str) -> None:
    program = f"import sys; sys.modules['playwright'] = None; {statement}"

    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", program], capture_output=True, text=True, check=False, timeout=300
    )

    assert result.returncode == 0, result.stderr[-2000:]
