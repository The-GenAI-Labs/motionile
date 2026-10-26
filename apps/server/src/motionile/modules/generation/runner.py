from uuid import UUID

from motionile.core.config import Settings
from motionile.modules.generation.exceptions import PipelineNotWiredError
from motionile.modules.generation.ports import PipelineRunner, ResumeKind


class RunnerRegistry:
    def __init__(self) -> None:
        self._runner: PipelineRunner | None = None

    def install(self, runner: PipelineRunner) -> None:
        self._runner = runner

    def clear(self) -> None:
        self._runner = None

    def current(self) -> PipelineRunner:
        if self._runner is None:
            raise PipelineNotWiredError
        return self._runner


registry = RunnerRegistry()


def install_runner(runner: PipelineRunner) -> None:
    registry.install(runner)


def runner_for(settings: Settings) -> PipelineRunner:
    del settings
    return registry.current()


class LazyPipelineRunner:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._runner: PipelineRunner | None = None

    def _current(self) -> PipelineRunner:
        if self._runner is None:
            from motionile.modules.generation.runner_impl import build_runner  # noqa: PLC0415

            self._runner = build_runner(self._settings)
        return self._runner

    async def run(self, job_id: UUID) -> None:
        await self._current().run(job_id)

    async def resume(self, job_id: UUID, kind: ResumeKind, instructions: str | None) -> None:
        await self._current().resume(job_id, kind, instructions)
