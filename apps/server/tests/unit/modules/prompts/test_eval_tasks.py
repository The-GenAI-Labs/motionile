from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.tasks.registry import Queue, RegisteredTask
from motionile.modules.prompts import tasks
from motionile.modules.prompts.domain import EvalQueue


def bare_name(name: str) -> str:
    return name.rpartition(":")[2]


def test_generation_suites_run_on_the_generation_queue_and_browser_suites_on_the_render_queue() -> None:
    assert tasks.run_eval.queue == Queue.GENERATION.value
    assert tasks.run_eval_browser.queue == Queue.RENDER.value
    assert bare_name(tasks.run_eval.name) == "prompts.run_eval"
    assert bare_name(tasks.run_eval_browser.name) == "prompts.run_eval_browser"


@pytest.mark.parametrize(
    ("queue", "expected"),
    [(EvalQueue.GENERATION, "prompts.run_eval"), (EvalQueue.BROWSER, "prompts.run_eval_browser")],
)
def test_deferral_picks_the_task_of_the_queue(monkeypatch: pytest.MonkeyPatch, queue: EvalQueue, expected: str) -> None:
    deferred: list[tuple[str, dict[str, str]]] = []

    def capture(session: AsyncSession, registered: RegisteredTask, **arguments: str) -> None:
        del session
        deferred.append((bare_name(registered.name), arguments))

    monkeypatch.setattr(tasks, "defer_after_commit", capture)
    run_id = uuid4()

    tasks.defer_eval_run(cast("AsyncSession", object()), run_id, queue)

    assert deferred == [(expected, {"run_id": str(run_id)})]
