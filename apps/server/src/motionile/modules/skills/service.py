import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from uuid import UUID

import structlog

from motionile.core.pagination import Cursor
from motionile.engine.ai.llm.models import LlmError
from motionile.engine.ai.ports import SkillLayer
from motionile.engine.ai.skills.loader import SkillDocument, SkillLibraryError, load_library
from motionile.modules.audit import ActorType, AuditContext, AuditEvent
from motionile.modules.audit import record as record_audit
from motionile.modules.skills.domain import AUDIT_TARGET, SkillAction
from motionile.modules.skills.exceptions import (
    SkillEmbeddingUnavailableError,
    SkillLibraryInvalidError,
    SkillNotFoundError,
)
from motionile.modules.skills.repository import SkillRecord, StoreFactory, Transaction
from motionile.modules.skills.schemas import ReseedView, SkillDetailView, SkillView
from motionile.modules.skills.seed import SkillSeeder
from motionile.modules.skills.views import detail_view, skill_view

logger = structlog.get_logger(__name__)

type LibraryLoader = Callable[[], Awaitable[Sequence[SkillDocument]]]


@dataclass(frozen=True, slots=True)
class SkillListing:
    items: list[SkillView]
    next_cursor: Cursor | None


async def load_shipped_library() -> Sequence[SkillDocument]:
    return await asyncio.to_thread(load_library)


def next_cursor_of(rows: list[SkillRecord], limit: int) -> Cursor | None:
    shown = rows[:limit]
    if len(rows) > limit and shown:
        return Cursor(shown[-1].created_at, shown[-1].id)
    return None


class SkillsService:
    def __init__(
        self,
        *,
        transaction: Transaction,
        store_factory: StoreFactory,
        seeder: SkillSeeder,
        embedding_model: str,
        library: LibraryLoader = load_shipped_library,
    ) -> None:
        self._transaction = transaction
        self._store_factory = store_factory
        self._seeder = seeder
        self._embedding_model = embedding_model
        self._library = library

    async def list_skills(self, layer: SkillLayer | None, cursor: Cursor | None, limit: int) -> SkillListing:
        async with self._transaction() as session:
            rows = await self._store_factory(session).page(layer.value if layer is not None else None, cursor, limit)
        return SkillListing(
            [skill_view(row, self._embedding_model) for row in rows[:limit]], next_cursor_of(rows, limit)
        )

    async def get_skill(self, slug: str) -> SkillDetailView:
        async with self._transaction() as session:
            store = self._store_factory(session)
            record = await store.record_of(slug)
            if record is None:
                raise SkillNotFoundError
            versions = await store.versions_of(record.id)
        return detail_view(record, versions, self._embedding_model)

    async def reseed(self, actor_id: UUID, context: AuditContext) -> ReseedView:
        try:
            library = await self._library()
        except SkillLibraryError as error:
            logger.error("skills.library_invalid", problems=list(error.problems))
            raise SkillLibraryInvalidError from error
        try:
            report = await self._seeder.sync(library)
        except LlmError as error:
            logger.warning("skills.reseed_embedding_failed", code=error.code.value)
            raise SkillEmbeddingUnavailableError from error
        async with self._transaction() as session:
            await record_audit(
                session,
                AuditEvent(
                    action=SkillAction.RESEEDED.value,
                    actor_type=ActorType.ADMIN,
                    actor_user_id=actor_id,
                    target_type=AUDIT_TARGET,
                    metadata={
                        "created": report.created,
                        "updated": report.updated,
                        "unchanged": report.unchanged,
                        "embedded": report.embedded,
                    },
                ),
                context,
            )
        return ReseedView(
            created=report.created, updated=report.updated, unchanged=report.unchanged, embedded=report.embedded
        )
