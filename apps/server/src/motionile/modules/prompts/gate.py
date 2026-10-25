from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.modules.prompts.exceptions import PromptTemplateNotFoundError, PromptVersionNotFoundError
from motionile.modules.prompts.repository import FinishedRun, SqlPromptRepository, StoreFactory

REQUIRED_SUITES: Final[Mapping[str, tuple[str, ...]]] = {
    "guard.input": ("safety",),
    "guard.output": ("safety",),
    "router.skills": ("planner", "safety"),
    "planner.storyboard": ("planner", "safety", "cost"),
    "critic.storyboard": ("planner", "safety", "cost"),
    "scene.module": ("scenes", "sync", "safety", "cost"),
    "repair.scene": ("scenes", "sync", "safety", "cost"),
    "review.vision": ("scenes",),
}
KNOWN_SUITES: Final[frozenset[str]] = frozenset(suite for suites in REQUIRED_SUITES.values() for suite in suites)


@dataclass(frozen=True, slots=True)
class SuiteResult:
    suite: str
    run_id: UUID
    dataset_version: str
    scores: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class GateVerdict:
    required: tuple[str, ...]
    passed: tuple[SuiteResult, ...]
    failed: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def activatable(self) -> bool:
        return bool(self.required) and not self.failed and not self.missing

    @property
    def complete(self) -> bool:
        return not self.missing

    def report(self) -> dict[str, Any]:
        return {
            "required": list(self.required),
            "passed": [
                {
                    "suite": result.suite,
                    "run_id": str(result.run_id),
                    "dataset_version": result.dataset_version,
                    "scores": dict(result.scores),
                }
                for result in self.passed
            ],
            "failed": list(self.failed),
            "missing": list(self.missing),
        }


def required_suites_of(key: str) -> tuple[str, ...]:
    suites = REQUIRED_SUITES.get(key)
    if suites is None:
        raise PromptTemplateNotFoundError
    return suites


def judge(required: Sequence[str], runs: Sequence[FinishedRun]) -> GateVerdict:
    passed: list[SuiteResult] = []
    failed: list[str] = []
    missing: list[str] = []
    for suite in required:
        covering = [run for run in runs if run.suite == suite]
        passing = next((run for run in covering if run.passed), None)
        if passing is not None:
            passed.append(SuiteResult(suite, passing.id, passing.dataset_version, passing.scores))
        elif covering:
            failed.append(suite)
        else:
            missing.append(suite)
    return GateVerdict(tuple(required), tuple(passed), tuple(failed), tuple(missing))


class ActivationGate:
    def __init__(self, store_factory: StoreFactory = SqlPromptRepository) -> None:
        self._store_factory = store_factory

    async def check(self, session: AsyncSession, version_id: UUID) -> GateVerdict:
        repository = self._store_factory(session)
        version = await repository.version_by_id(version_id)
        if version is None:
            raise PromptVersionNotFoundError
        template = await repository.template_by_id(version.template_id)
        if template is None:
            raise PromptTemplateNotFoundError
        runs = await repository.finished_runs_covering(version.id, version.created_at)
        return judge(required_suites_of(template.key), runs)
