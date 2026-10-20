import subprocess
import sys
from typing import Any, cast
from uuid import UUID

import pytest
from procrastinate import RetryStrategy
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.tasks.registry import Queue, blueprint
from motionile.modules.media import tasks


def registered() -> dict[str, Any]:
    tasks = cast("dict[str, Any]", cast("Any", blueprint).tasks)
    return {task.name.removeprefix("motionile:"): task for task in tasks.values()}


def test_the_render_run_task_uses_the_render_queue_with_three_attempts() -> None:
    task = registered()["render.run"]

    assert task.queue == Queue.RENDER.value
    assert isinstance(task.retry_strategy, RetryStrategy)
    assert task.retry_strategy.max_attempts == 3


def test_the_sweeper_and_the_cache_pruner_run_on_the_default_queue() -> None:
    assert registered()["media.fail_stalled_renders"].queue == Queue.DEFAULT.value
    assert registered()["media.prune_tts_cache"].queue == Queue.DEFAULT.value


def test_the_sweeper_is_scheduled_every_five_minutes() -> None:
    schedules = {
        periodic.task.name.removeprefix("motionile:"): periodic.cron
        for periodic in cast("Any", blueprint.periodic_registry).periodic_tasks.values()
    }

    assert schedules["media.fail_stalled_renders"] == "*/5 * * * *"


def test_deferring_a_render_goes_through_the_after_commit_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[tuple[object, dict[str, object]]] = []

    def capture(session: AsyncSession, task: object, **arguments: object) -> None:
        del session
        recorded.append((task, arguments))

    monkeypatch.setattr(tasks, "defer_after_commit", capture)

    tasks.dispatch_render(AsyncSession(), UUID(int=4))

    assert recorded == [(tasks.run_render, {"render_id": str(UUID(int=4))})]


def test_importing_the_module_and_its_tasks_does_not_load_the_browser_stack() -> None:
    script = "import sys, motionile.modules.media, motionile.modules.media.tasks; sys.exit('playwright' in sys.modules)"

    completed = subprocess.run([sys.executable, "-c", script], check=False, capture_output=True)  # noqa: S603

    assert completed.returncode == 0
