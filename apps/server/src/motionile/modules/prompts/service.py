import asyncio
from dataclasses import dataclass

from motionile.core.pagination import Cursor
from motionile.engine.ai.prompts.canary import new_canary
from motionile.modules.prompts.activation import switch_active
from motionile.modules.prompts.auditing import audit
from motionile.modules.prompts.diffing import diff_bodies
from motionile.modules.prompts.domain import (
    AUDIT_TEMPLATE_TARGET,
    Activation,
    ActivationKind,
    Actor,
    EvalStatus,
    PromptAction,
    Subject,
    previous_version_id,
)
from motionile.modules.prompts.drafts import validate_draft
from motionile.modules.prompts.exceptions import (
    ActivationBlockedError,
    DraftExistsError,
    NoPreviousVersionError,
    PromptTemplateNotFoundError,
    PromptVersionNotFoundError,
)
from motionile.modules.prompts.gate import ActivationGate
from motionile.modules.prompts.models import PromptTemplate, PromptVersion
from motionile.modules.prompts.repository import NewVersion, PromptRepository, StoreFactory, Transaction
from motionile.modules.prompts.schemas import DiffView, DraftRequest, TemplateView, VersionView
from motionile.modules.prompts.views import template_view, version_view


@dataclass(frozen=True, slots=True)
class VersionListing:
    items: list[VersionView]
    next_cursor: Cursor | None


async def locked_template(repository: PromptRepository, key: str) -> PromptTemplate:
    template = await repository.template(key, lock=True)
    if template is None:
        raise PromptTemplateNotFoundError
    return template


async def numbered_version(repository: PromptRepository, template: PromptTemplate, number: int) -> PromptVersion:
    version = await repository.version(template.id, number)
    if version is None:
        raise PromptVersionNotFoundError
    return version


class PromptsService:
    def __init__(self, *, transaction: Transaction, store_factory: StoreFactory, gate: ActivationGate) -> None:
        self._transaction = transaction
        self._store_factory = store_factory
        self._gate = gate

    async def list_templates(self) -> list[TemplateView]:
        async with self._transaction() as session:
            summaries = await self._store_factory(session).summaries()
        return [template_view(summary) for summary in summaries]

    async def list_versions(self, key: str, cursor: Cursor | None, limit: int) -> VersionListing:
        async with self._transaction() as session:
            repository = self._store_factory(session)
            template = await repository.template(key)
            if template is None:
                raise PromptTemplateNotFoundError
            rows = await repository.page_versions(template.id, cursor, limit)
        shown = rows[:limit]
        next_cursor = Cursor(shown[-1].created_at, shown[-1].id) if len(rows) > limit and shown else None
        return VersionListing([version_view(row, template.active_version_id) for row in shown], next_cursor)

    async def diff(self, actor: Actor, key: str, from_number: int, to_number: int) -> DiffView:
        async with self._transaction() as session:
            repository = self._store_factory(session)
            template = await repository.template(key)
            if template is None:
                raise PromptTemplateNotFoundError
            older = await numbered_version(repository, template, from_number)
            newer = await numbered_version(repository, template, to_number)
            await audit(
                session,
                actor,
                PromptAction.DIFF_VIEWED,
                Subject(AUDIT_TEMPLATE_TARGET, template.id),
                {"key": key, "from_version": from_number, "to_version": to_number},
            )
            older_body, newer_body = older.body, newer.body
            canaries = [older.canary, newer.canary]
        computed = await asyncio.to_thread(
            diff_bodies,
            older_body,
            newer_body,
            canaries,
            older_label=f"v{from_number}",
            newer_label=f"v{to_number}",
        )
        return DiffView(
            key=key,
            from_version=from_number,
            to_version=to_number,
            lines=computed.lines,
            added=computed.added,
            removed=computed.removed,
        )

    async def create_draft(self, actor: Actor, key: str, request: DraftRequest) -> VersionView:
        draft = validate_draft(request.body, request.variables)
        async with self._transaction() as session:
            repository = self._store_factory(session)
            template = await locked_template(repository, key)
            if await repository.version_by_checksum(template.id, draft.checksum) is not None:
                raise DraftExistsError
            number = await repository.latest_number(template.id) + 1
            version = await repository.insert_version(
                NewVersion(
                    template_id=template.id,
                    number=number,
                    body=draft.body,
                    variables=draft.variables,
                    checksum=draft.checksum,
                    canary=new_canary(),
                    created_by=actor.user_id,
                )
            )
            await audit(
                session,
                actor,
                PromptAction.DRAFT_CREATED,
                Subject(AUDIT_TEMPLATE_TARGET, template.id),
                {"key": key, "version": number, "version_id": str(version.id), "source": "admin"},
            )
            return version_view(version, template.active_version_id)

    async def activate(self, actor: Actor, key: str, number: int) -> VersionView:
        async with self._transaction() as session:
            repository = self._store_factory(session)
            template = await locked_template(repository, key)
            version = await numbered_version(repository, template, number)
            if template.active_version_id == version.id:
                return version_view(version, version.id)
            verdict = await self._gate.check(session, version.id)
            if not verdict.activatable:
                raise ActivationBlockedError(verdict.missing, verdict.failed)
            await repository.set_eval_result(version.id, EvalStatus.PASSED.value, verdict.report())
            await switch_active(
                session,
                repository,
                template,
                version,
                Activation(
                    ActivationKind.ACTIVATED,
                    actor,
                    {"eval_run_ids": [str(result.run_id) for result in verdict.passed]},
                ),
            )
            refreshed = await numbered_version(repository, template, number)
            return version_view(refreshed, refreshed.id)

    async def rollback(self, actor: Actor, key: str) -> VersionView:
        async with self._transaction() as session:
            repository = self._store_factory(session)
            template = await locked_template(repository, key)
            current = template.active_version_id
            if current is None:
                raise NoPreviousVersionError("The template has no active version.")
            previous_id = previous_version_id(await repository.activation_events(template.id), current)
            target = await repository.version_by_id(previous_id) if previous_id is not None else None
            if target is None:
                raise NoPreviousVersionError
            await switch_active(session, repository, template, target, Activation(ActivationKind.ROLLED_BACK, actor))
            return version_view(target, target.id)
