from collections.abc import Iterator
from pathlib import Path

import pytest
import structlog
from hypothesis import settings as hypothesis_settings

from motionile.core.config import get_settings

hypothesis_settings.register_profile("motionile", deadline=None, derandomize=True, database=None, print_blob=True)
hypothesis_settings.load_profile("motionile")

TESTS_ROOT = Path(__file__).parent
MARKER_BY_DIRECTORY = {"unit": pytest.mark.unit, "integration": pytest.mark.integration}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        relative = item.path.relative_to(TESTS_ROOT)
        marker = MARKER_BY_DIRECTORY.get(relative.parts[0])
        if marker is not None:
            item.add_marker(marker)


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    structlog.contextvars.clear_contextvars()
    yield
    get_settings.cache_clear()
    structlog.contextvars.clear_contextvars()
    structlog.reset_defaults()
