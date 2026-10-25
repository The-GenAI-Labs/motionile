from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from motionile.core.resources import Resources


@dataclass(frozen=True, slots=True)
class EvalOutcome:
    scores: Mapping[str, Any]
    passed: bool
    dataset_version: str
    model_configuration: Mapping[str, Any]


class EvalExecutionError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class EvalExecutor(Protocol):
    async def execute(self, run_id: UUID, suite: str, version_ids: Sequence[UUID]) -> EvalOutcome: ...


type EvalExecutorFactory = Callable[[Resources], EvalExecutor]


class InstalledExecutor:
    def __init__(self) -> None:
        self.factory: EvalExecutorFactory | None = None


installed = InstalledExecutor()


def install_eval_executor(factory: EvalExecutorFactory | None) -> None:
    installed.factory = factory


def eval_executor_for(resources: Resources) -> EvalExecutor | None:
    factory = installed.factory
    return factory(resources) if factory is not None else None
