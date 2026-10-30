from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import FrozenClock
from motionile.core.db import run_after_commit, run_after_rollback
from motionile.core.ids import new_id
from motionile.core.pagination import Cursor
from motionile.engine.ai.ports import ActivePrompt
from motionile.modules.audit import AuditEvent
from motionile.modules.prompts.domain import (
    AUDIT_TEMPLATE_TARGET,
    ActivationEvent,
    activation_event_of,
)
from motionile.modules.prompts.models import EvalRun, PromptTemplate, PromptVersion
from motionile.modules.prompts.repository import (
    FinishedRun,
    NewRun,
    NewVersion,
    RunFilter,
    RunResult,
    TemplateSummary,
)

EPOCH = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
TICK = timedelta(seconds=1)


@dataclass
class PromptWorld:
    clock: FrozenClock = field(default_factory=lambda: FrozenClock(EPOCH))
    templates: dict[UUID, PromptTemplate] = field(default_factory=dict[UUID, PromptTemplate])
    versions: dict[UUID, PromptVersion] = field(default_factory=dict[UUID, PromptVersion])
    runs: dict[UUID, EvalRun] = field(default_factory=dict[UUID, EvalRun])
    audit: list[AuditEvent] = field(default_factory=list[AuditEvent])
    transactions: int = 0

    def store(self, session: AsyncSession) -> "InMemoryPromptRepository":
        del session
        return InMemoryPromptRepository(self)

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession]:
        self.transactions += 1
        session = AsyncSession()
        try:
            yield session
        except BaseException:
            await run_after_rollback(session)
            raise
        else:
            await run_after_commit(session)

    def stamp(self) -> datetime:
        self.clock.advance(TICK)
        return self.clock.now()

    def template_by_key(self, key: str) -> PromptTemplate:
        return next(template for template in self.templates.values() if template.key == key)

    def versions_of(self, key: str) -> list[PromptVersion]:
        template = self.template_by_key(key)
        return sorted(
            (version for version in self.versions.values() if version.template_id == template.id),
            key=lambda version: version.version,
        )

    def add_run(
        self,
        version_ids: Sequence[UUID],
        suite: str,
        *,
        passed: bool | None = True,
        status: str = "finished",
        started_at: datetime | None = None,
    ) -> EvalRun:
        stamp = self.stamp()
        finished = status != "running"
        run = EvalRun(
            id=new_id(),
            suite=suite,
            dataset_version="2026.10",
            prompt_version_ids=list(version_ids),
            models_used={},
            scores={"accuracy": 0.9},
            passed=passed if status == "finished" else None,
            status=status,
            error_code="boom_failure" if status == "errored" else None,
            trigger="ci",
            created_by=None,
            started_at=started_at or stamp,
            finished_at=stamp if finished else None,
            created_at=stamp,
            updated_at=stamp,
        )
        self.runs[run.id] = run
        return run

    def pass_all(self, key: str, suites: Sequence[str], version: int | None = None) -> PromptVersion:
        target = self.versions_of(key)[-1] if version is None else self.versions_of(key)[version - 1]
        for suite in suites:
            self.add_run([target.id], suite, passed=True)
        return target


def assert_run_consistent(run: EvalRun) -> None:
    assert run.status in {"running", "finished", "errored"}
    assert (run.status == "running") == (run.finished_at is None)
    assert (run.status == "finished") == (run.passed is not None)
    assert (run.status == "errored") == (run.error_code is not None)
    assert run.trigger in {"ci", "nightly", "admin"}
    assert len(run.prompt_version_ids) <= 100


class InMemoryPromptRepository:
    def __init__(self, world: PromptWorld) -> None:
        self._world = world

    async def template(self, key: str, *, lock: bool = False) -> PromptTemplate | None:
        del lock
        return next((template for template in self._world.templates.values() if template.key == key), None)

    async def template_by_id(self, template_id: UUID) -> PromptTemplate | None:
        return self._world.templates.get(template_id)

    async def ensure_template(self, key: str, description: str | None) -> tuple[PromptTemplate, bool]:
        existing = await self.template(key)
        if existing is not None:
            return existing, False
        stamp = self._world.stamp()
        template = PromptTemplate(
            id=new_id(), key=key, description=description, active_version_id=None, created_at=stamp, updated_at=stamp
        )
        self._world.templates[template.id] = template
        return template, True

    async def summaries(self) -> list[TemplateSummary]:
        summaries: list[TemplateSummary] = []
        for template in sorted(self._world.templates.values(), key=lambda row: row.key):
            versions = self._world.versions_of(template.key)
            active = self._world.versions.get(template.active_version_id) if template.active_version_id else None
            summaries.append(
                TemplateSummary(
                    template.key,
                    template.description,
                    active.version if active is not None else None,
                    len(versions),
                    versions[-1].eval_status if versions else None,
                )
            )
        return summaries

    async def version(self, template_id: UUID, number: int) -> PromptVersion | None:
        return next(
            (
                version
                for version in self._world.versions.values()
                if version.template_id == template_id and version.version == number
            ),
            None,
        )

    async def version_by_id(self, version_id: UUID) -> PromptVersion | None:
        return self._world.versions.get(version_id)

    async def versions_by_ids(self, version_ids: Sequence[UUID]) -> list[PromptVersion]:
        return [self._world.versions[version_id] for version_id in version_ids if version_id in self._world.versions]

    async def version_by_checksum(self, template_id: UUID, checksum: bytes) -> PromptVersion | None:
        return next(
            (
                version
                for version in self._world.versions.values()
                if version.template_id == template_id and version.checksum == checksum
            ),
            None,
        )

    async def latest_number(self, template_id: UUID) -> int:
        numbers = [v.version for v in self._world.versions.values() if v.template_id == template_id]
        return max(numbers, default=0)

    async def latest_version(self, template_id: UUID) -> PromptVersion | None:
        number = await self.latest_number(template_id)
        return await self.version(template_id, number) if number else None

    async def insert_version(self, row: NewVersion) -> PromptVersion:
        stamp = self._world.stamp()
        version = PromptVersion(
            id=new_id(),
            template_id=row.template_id,
            version=row.number,
            body=row.body,
            variables=list(row.variables),
            checksum=row.checksum,
            canary=row.canary,
            eval_status="pending",
            eval_report=None,
            created_by=row.created_by,
            created_at=stamp,
            updated_at=stamp,
        )
        self._world.versions[version.id] = version
        return version

    async def page_versions(self, template_id: UUID, cursor: Cursor | None, limit: int) -> list[PromptVersion]:
        rows = sorted(
            (
                version
                for version in self._world.versions.values()
                if version.template_id == template_id
                and (cursor is None or (version.created_at, version.id) < (cursor.created_at, cursor.id))
            ),
            key=lambda version: (version.created_at, version.id),
            reverse=True,
        )
        return rows[: limit + 1]

    async def set_active(self, template_id: UUID, version_id: UUID, expected: UUID | None) -> bool:
        template = self._world.templates[template_id]
        if template.active_version_id != expected:
            return False
        template.active_version_id = version_id
        return True

    async def set_eval_result(self, version_id: UUID, status: str, report: Mapping[str, Any]) -> None:
        version = self._world.versions[version_id]
        version.eval_status = status
        version.eval_report = dict(report)

    async def active_prompt(self, key: str) -> ActivePrompt | None:
        template = await self.template(key)
        if template is None or template.active_version_id is None:
            return None
        return self._active(template)

    async def active_prompts(self) -> list[ActivePrompt]:
        return [
            self._active(template)
            for template in sorted(self._world.templates.values(), key=lambda row: row.key)
            if template.active_version_id is not None
        ]

    def _active(self, template: PromptTemplate) -> ActivePrompt:
        assert template.active_version_id is not None
        version = self._world.versions[template.active_version_id]
        return ActivePrompt(
            key=template.key,
            version_id=version.id,
            version=version.version,
            body=version.body,
            canary=version.canary,
            variables=tuple(version.variables),
        )

    async def activation_events(self, template_id: UUID) -> list[ActivationEvent]:
        events = (
            activation_event_of(event.action, event.metadata)
            for event in self._world.audit
            if event.target_type == AUDIT_TEMPLATE_TARGET and event.target_id == str(template_id)
        )
        return [event for event in events if event is not None]

    async def finished_runs_covering(self, version_id: UUID, started_after: datetime) -> list[FinishedRun]:
        runs = sorted(
            (
                run
                for run in self._world.runs.values()
                if run.status == "finished" and version_id in run.prompt_version_ids and run.started_at > started_after
            ),
            key=lambda run: run.started_at,
            reverse=True,
        )
        return [
            FinishedRun(run.id, run.suite, run.passed is True, run.dataset_version, run.scores, run.started_at)
            for run in runs
        ]

    async def insert_run(self, row: NewRun) -> EvalRun:
        stamp = self._world.stamp()
        run = EvalRun(
            id=new_id(),
            suite=row.suite,
            dataset_version=row.dataset_version,
            prompt_version_ids=list(row.prompt_version_ids),
            models_used=dict(row.models_used or {}),
            scores=dict(row.scores or {}),
            passed=row.passed,
            status=row.status.value,
            error_code=row.error_code,
            trigger=row.trigger,
            created_by=row.created_by,
            started_at=row.started_at or stamp,
            finished_at=row.finished_at,
            created_at=stamp,
            updated_at=stamp,
        )
        assert_run_consistent(run)
        self._world.runs[run.id] = run
        return run

    async def run(self, run_id: UUID) -> EvalRun | None:
        return self._world.runs.get(run_id)

    async def page_runs(self, run_filter: RunFilter, cursor: Cursor | None, limit: int) -> list[EvalRun]:
        rows = sorted(
            (
                run
                for run in self._world.runs.values()
                if (run_filter.suite is None or run.suite == run_filter.suite)
                and (run_filter.status is None or run.status == run_filter.status)
                and (cursor is None or (run.created_at, run.id) < (cursor.created_at, cursor.id))
            ),
            key=lambda run: (run.created_at, run.id),
            reverse=True,
        )
        return rows[: limit + 1]

    async def finish_run(self, run_id: UUID, result: RunResult, finished_at: datetime) -> bool:
        run = self._world.runs.get(run_id)
        if run is None or run.status != "running":
            return False
        run.status = "finished"
        run.passed = result.passed
        run.scores = dict(result.scores)
        run.models_used = dict(result.models_used)
        run.dataset_version = result.dataset_version
        run.finished_at = finished_at
        assert_run_consistent(run)
        return True

    async def fail_run(self, run_id: UUID, error_code: str, finished_at: datetime) -> bool:
        run = self._world.runs.get(run_id)
        if run is None or run.status != "running":
            return False
        run.status = "errored"
        run.error_code = error_code
        run.finished_at = finished_at
        assert_run_consistent(run)
        return True
