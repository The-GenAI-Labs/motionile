from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import Select, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from motionile.core.ids import new_id
from motionile.core.pagination import Cursor, keyset_page
from motionile.engine.ai.ports import ActivePrompt
from motionile.modules.audit import AuditLogEntry
from motionile.modules.prompts.domain import (
    ACTIVATION_ACTIONS,
    AUDIT_TEMPLATE_TARGET,
    ActivationEvent,
    RunStatus,
    activation_event_of,
)
from motionile.modules.prompts.models import EvalRun, PromptTemplate, PromptVersion

FRESH_ROWS = {"populate_existing": True}

type Transaction = Callable[[], AbstractAsyncContextManager[AsyncSession]]
type StoreFactory = Callable[[AsyncSession], PromptRepository]


@dataclass(frozen=True, slots=True)
class TemplateSummary:
    key: str
    description: str | None
    active_version: int | None
    version_count: int
    latest_eval_status: str | None


@dataclass(frozen=True, slots=True)
class NewVersion:
    template_id: UUID
    number: int
    body: str
    variables: Sequence[str]
    checksum: bytes
    canary: str
    created_by: UUID | None


@dataclass(frozen=True, slots=True)
class NewRun:
    suite: str
    dataset_version: str
    prompt_version_ids: Sequence[UUID]
    trigger: str
    created_by: UUID | None
    status: RunStatus = RunStatus.RUNNING
    models_used: Mapping[str, Any] | None = None
    scores: Mapping[str, Any] | None = None
    passed: bool | None = None
    error_code: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RunResult:
    dataset_version: str
    models_used: Mapping[str, Any]
    scores: Mapping[str, Any]
    passed: bool


@dataclass(frozen=True, slots=True)
class FinishedRun:
    id: UUID
    suite: str
    passed: bool
    dataset_version: str
    scores: Mapping[str, Any]
    started_at: datetime


@dataclass(frozen=True, slots=True)
class RunFilter:
    suite: str | None = None
    status: str | None = None


class PromptRepository(Protocol):
    async def template(self, key: str, *, lock: bool = False) -> PromptTemplate | None: ...

    async def template_by_id(self, template_id: UUID) -> PromptTemplate | None: ...

    async def ensure_template(self, key: str, description: str | None) -> tuple[PromptTemplate, bool]: ...

    async def summaries(self) -> list[TemplateSummary]: ...

    async def version(self, template_id: UUID, number: int) -> PromptVersion | None: ...

    async def version_by_id(self, version_id: UUID) -> PromptVersion | None: ...

    async def versions_by_ids(self, version_ids: Sequence[UUID]) -> list[PromptVersion]: ...

    async def version_by_checksum(self, template_id: UUID, checksum: bytes) -> PromptVersion | None: ...

    async def latest_number(self, template_id: UUID) -> int: ...

    async def latest_version(self, template_id: UUID) -> PromptVersion | None: ...

    async def insert_version(self, row: NewVersion) -> PromptVersion: ...

    async def page_versions(self, template_id: UUID, cursor: Cursor | None, limit: int) -> list[PromptVersion]: ...

    async def set_active(self, template_id: UUID, version_id: UUID, expected: UUID | None) -> bool: ...

    async def set_eval_result(self, version_id: UUID, status: str, report: Mapping[str, Any]) -> None: ...

    async def active_prompt(self, key: str) -> ActivePrompt | None: ...

    async def active_prompts(self) -> list[ActivePrompt]: ...

    async def activation_events(self, template_id: UUID) -> list[ActivationEvent]: ...

    async def finished_runs_covering(self, version_id: UUID, started_after: datetime) -> list[FinishedRun]: ...

    async def insert_run(self, row: NewRun) -> EvalRun: ...

    async def run(self, run_id: UUID) -> EvalRun | None: ...

    async def page_runs(self, run_filter: RunFilter, cursor: Cursor | None, limit: int) -> list[EvalRun]: ...

    async def finish_run(self, run_id: UUID, result: RunResult, finished_at: datetime) -> bool: ...

    async def fail_run(self, run_id: UUID, error_code: str, finished_at: datetime) -> bool: ...


def active_prompt_of(row: Any) -> ActivePrompt:
    return ActivePrompt(
        key=row.key,
        version_id=row.id,
        version=row.version,
        body=row.body,
        canary=row.canary,
        variables=tuple(row.variables),
    )


def active_prompt_statement() -> Select[str, UUID, int, str, str, list[str]]:
    return select(
        PromptTemplate.key,
        PromptVersion.id,
        PromptVersion.version,
        PromptVersion.body,
        PromptVersion.canary,
        PromptVersion.variables,
    ).join(PromptVersion, PromptVersion.id == PromptTemplate.active_version_id)


class SqlPromptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def template(self, key: str, *, lock: bool = False) -> PromptTemplate | None:
        statement = select(PromptTemplate).where(PromptTemplate.key == key).execution_options(**FRESH_ROWS)
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def template_by_id(self, template_id: UUID) -> PromptTemplate | None:
        statement = select(PromptTemplate).where(PromptTemplate.id == template_id).execution_options(**FRESH_ROWS)
        return await self.session.scalar(statement)

    async def ensure_template(self, key: str, description: str | None) -> tuple[PromptTemplate, bool]:
        statement = (
            pg_insert(PromptTemplate)
            .values(id=new_id(), key=key, description=description)
            .on_conflict_do_nothing(index_elements=[PromptTemplate.key])
            .returning(PromptTemplate.id)
        )
        created = await self.session.scalar(statement) is not None
        template = await self.template(key)
        if template is None:
            message = "the prompt template vanished after it was ensured"
            raise LookupError(message)
        return template, created

    async def summaries(self) -> list[TemplateSummary]:
        active = aliased(PromptVersion)
        templates = await self.session.execute(
            select(PromptTemplate.id, PromptTemplate.key, PromptTemplate.description, active.version)
            .outerjoin(active, active.id == PromptTemplate.active_version_id)
            .order_by(PromptTemplate.key)
        )
        counts = dict(
            (
                await self.session.execute(
                    select(PromptVersion.template_id, func.count()).group_by(PromptVersion.template_id)
                )
            ).all()
        )
        latest = dict(
            (
                await self.session.execute(
                    select(PromptVersion.template_id, PromptVersion.eval_status)
                    .distinct(PromptVersion.template_id)
                    .order_by(PromptVersion.template_id, PromptVersion.version.desc())
                )
            ).all()
        )
        return [
            TemplateSummary(key, description, active_version, counts.get(template_id, 0), latest.get(template_id))
            for template_id, key, description, active_version in templates
        ]

    async def version(self, template_id: UUID, number: int) -> PromptVersion | None:
        statement = (
            select(PromptVersion)
            .where(PromptVersion.template_id == template_id, PromptVersion.version == number)
            .execution_options(**FRESH_ROWS)
        )
        return await self.session.scalar(statement)

    async def version_by_id(self, version_id: UUID) -> PromptVersion | None:
        statement = select(PromptVersion).where(PromptVersion.id == version_id).execution_options(**FRESH_ROWS)
        return await self.session.scalar(statement)

    async def versions_by_ids(self, version_ids: Sequence[UUID]) -> list[PromptVersion]:
        statement = select(PromptVersion).where(PromptVersion.id.in_(version_ids)).execution_options(**FRESH_ROWS)
        return list(await self.session.scalars(statement))

    async def version_by_checksum(self, template_id: UUID, checksum: bytes) -> PromptVersion | None:
        statement = select(PromptVersion).where(
            PromptVersion.template_id == template_id, PromptVersion.checksum == checksum
        )
        return await self.session.scalar(statement)

    async def latest_number(self, template_id: UUID) -> int:
        statement = select(func.max(PromptVersion.version)).where(PromptVersion.template_id == template_id)
        return int(await self.session.scalar(statement) or 0)

    async def latest_version(self, template_id: UUID) -> PromptVersion | None:
        statement = (
            select(PromptVersion)
            .where(PromptVersion.template_id == template_id)
            .order_by(PromptVersion.version.desc())
            .limit(1)
            .execution_options(**FRESH_ROWS)
        )
        return await self.session.scalar(statement)

    async def insert_version(self, row: NewVersion) -> PromptVersion:
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
        )
        self.session.add(version)
        await self.session.flush()
        await self.session.refresh(version)
        return version

    async def page_versions(self, template_id: UUID, cursor: Cursor | None, limit: int) -> list[PromptVersion]:
        statement = select(PromptVersion).where(PromptVersion.template_id == template_id)
        paged = keyset_page(
            statement, created_at=PromptVersion.created_at, id_=PromptVersion.id, cursor=cursor, limit=limit
        )
        return list(await self.session.scalars(paged.execution_options(**FRESH_ROWS)))

    async def set_active(self, template_id: UUID, version_id: UUID, expected: UUID | None) -> bool:
        statement = (
            update(PromptTemplate)
            .where(
                PromptTemplate.id == template_id,
                PromptTemplate.active_version_id.is_not_distinct_from(expected),
            )
            .values(active_version_id=version_id)
            .returning(PromptTemplate.id)
        )
        return await self.session.scalar(statement) is not None

    async def set_eval_result(self, version_id: UUID, status: str, report: Mapping[str, Any]) -> None:
        await self.session.execute(
            update(PromptVersion)
            .where(PromptVersion.id == version_id)
            .values(eval_status=status, eval_report=dict(report))
        )

    async def active_prompt(self, key: str) -> ActivePrompt | None:
        row = (await self.session.execute(active_prompt_statement().where(PromptTemplate.key == key))).first()
        return active_prompt_of(row) if row is not None else None

    async def active_prompts(self) -> list[ActivePrompt]:
        rows = await self.session.execute(active_prompt_statement().order_by(PromptTemplate.key))
        return [active_prompt_of(row) for row in rows]

    async def activation_events(self, template_id: UUID) -> list[ActivationEvent]:
        statement = (
            select(AuditLogEntry.action, AuditLogEntry.metadata_)
            .where(
                AuditLogEntry.target_type == AUDIT_TEMPLATE_TARGET,
                AuditLogEntry.target_id == str(template_id),
                AuditLogEntry.action.in_([action.value for action in ACTIVATION_ACTIONS.values()]),
            )
            .order_by(AuditLogEntry.created_at, AuditLogEntry.id)
        )
        events = (activation_event_of(action, metadata) for action, metadata in await self.session.execute(statement))
        return [event for event in events if event is not None]

    async def finished_runs_covering(self, version_id: UUID, started_after: datetime) -> list[FinishedRun]:
        statement = (
            select(
                EvalRun.id,
                EvalRun.suite,
                EvalRun.passed,
                EvalRun.dataset_version,
                EvalRun.scores,
                EvalRun.started_at,
            )
            .where(
                EvalRun.prompt_version_ids.contains([version_id]),
                EvalRun.status == RunStatus.FINISHED.value,
                EvalRun.started_at > started_after,
            )
            .order_by(EvalRun.started_at.desc(), EvalRun.id.desc())
        )
        return [
            FinishedRun(run_id, suite, passed is True, dataset_version, scores, started_at)
            for run_id, suite, passed, dataset_version, scores, started_at in await self.session.execute(statement)
        ]

    async def insert_run(self, row: NewRun) -> EvalRun:
        values: dict[str, Any] = {
            "id": new_id(),
            "suite": row.suite,
            "dataset_version": row.dataset_version,
            "prompt_version_ids": list(row.prompt_version_ids),
            "models_used": dict(row.models_used or {}),
            "scores": dict(row.scores or {}),
            "passed": row.passed,
            "status": row.status.value,
            "error_code": row.error_code,
            "trigger": row.trigger,
            "created_by": row.created_by,
            "finished_at": row.finished_at,
        }
        if row.started_at is not None:
            values["started_at"] = row.started_at
        run = EvalRun(**values)
        self.session.add(run)
        await self.session.flush()
        await self.session.refresh(run)
        return run

    async def run(self, run_id: UUID) -> EvalRun | None:
        statement = select(EvalRun).where(EvalRun.id == run_id).execution_options(**FRESH_ROWS)
        return await self.session.scalar(statement)

    async def page_runs(self, run_filter: RunFilter, cursor: Cursor | None, limit: int) -> list[EvalRun]:
        statement = select(EvalRun)
        if run_filter.suite is not None:
            statement = statement.where(EvalRun.suite == run_filter.suite)
        if run_filter.status is not None:
            statement = statement.where(EvalRun.status == run_filter.status)
        paged = keyset_page(statement, created_at=EvalRun.created_at, id_=EvalRun.id, cursor=cursor, limit=limit)
        return list(await self.session.scalars(paged.execution_options(**FRESH_ROWS)))

    async def finish_run(self, run_id: UUID, result: RunResult, finished_at: datetime) -> bool:
        statement = (
            update(EvalRun)
            .where(EvalRun.id == run_id, EvalRun.status == RunStatus.RUNNING.value)
            .values(
                {
                    EvalRun.status: RunStatus.FINISHED.value,
                    EvalRun.passed: result.passed,
                    EvalRun.scores: dict(result.scores),
                    EvalRun.models_used: dict(result.models_used),
                    EvalRun.dataset_version: result.dataset_version,
                    EvalRun.finished_at: finished_at,
                }
            )
            .returning(EvalRun.id)
        )
        return await self.session.scalar(statement) is not None

    async def fail_run(self, run_id: UUID, error_code: str, finished_at: datetime) -> bool:
        statement = (
            update(EvalRun)
            .where(EvalRun.id == run_id, EvalRun.status == RunStatus.RUNNING.value)
            .values(
                {
                    EvalRun.status: RunStatus.ERRORED.value,
                    EvalRun.error_code: error_code,
                    EvalRun.finished_at: finished_at,
                }
            )
            .returning(EvalRun.id)
        )
        return await self.session.scalar(statement) is not None
