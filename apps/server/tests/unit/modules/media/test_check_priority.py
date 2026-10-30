from typing import Any
from uuid import uuid4

import pytest

from motionile.modules.media import tasks


class ConfiguredCheck:
    def __init__(self) -> None:
        self.configuration: dict[str, Any] = {}
        self.deferred: dict[str, Any] = {}

    def configure(self, **configuration: Any) -> "ConfiguredCheck":
        self.configuration = configuration
        return self

    async def defer_async(self, **arguments: Any) -> None:
        self.deferred = arguments


async def test_composition_checks_queue_ahead_of_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = ConfiguredCheck()
    monkeypatch.setattr(tasks, "check_composition", recorder)
    job_id = uuid4()

    await tasks.defer_composition_check(job_id, "abc123")

    assert recorder.configuration == {"queueing_lock": "abc123", "priority": tasks.CHECK_PRIORITY}
    assert recorder.deferred == {"job_id": str(job_id), "check_id": "abc123"}
    assert tasks.CHECK_PRIORITY > 0
