import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from httpx import AsyncClient, Response
from sqlalchemy import text
from tests.fakes.generation import FakeEditGuard, RecordingDispatch, job_options
from tests.integration.credit_support import purge_credit_data
from tests.integration.media_support import MediaApi
from tests.integration.test_auth import csrf
from tests.unit.modules.generation.support import storyboard_content

from motionile.core.db import Database
from motionile.core.ids import new_id
from motionile.modules.credits import CreditRef, CreditsService, GrantCommand
from motionile.modules.generation.checkpoints import PostgresCheckpointPurger
from motionile.modules.generation.lookups import (
    CatalogTopicLookup,
    SkillsStyleLookup,
    SqlPreferencesLookup,
    VoiceCatalogChoices,
)
from motionile.modules.generation.options import OptionResolver
from motionile.modules.generation.ports import JobDispatch
from motionile.modules.generation.runtime_settings import PlatformSettingsReader, RuntimeSettings
from motionile.modules.generation.service import GenerationDeps, GenerationService
from motionile.modules.media import media_service_for, music_service_for
from motionile.modules.voices import VoiceLookupImpl

JOBS = "/v1/jobs"
STYLE = "minimal-dark"
TERMINAL = ("completed", "failed", "cancelled")
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


@dataclass
class GenerationApi:
    media: MediaApi
    service: GenerationService
    dispatch: RecordingDispatch
    guard: FakeEditGuard
    voice_id: UUID

    @property
    def database(self) -> Database:
        return self.media.database

    @property
    def primary(self) -> AsyncClient:
        return self.media.primary

    @property
    def other(self) -> AsyncClient:
        return self.media.other

    @property
    def primary_id(self) -> UUID:
        return self.media.primary_id

    @property
    def other_id(self) -> UUID:
        return self.media.other_id

    async def fund(self, user_id: UUID, amount: int) -> None:
        resources = self.media.resources
        service = CreditsService(resources.clock, resources.settings.billing)
        async with self.database.transaction() as session:
            await service.grant(
                session,
                GrantCommand(
                    user_id=user_id,
                    amount=amount,
                    source="purchase",
                    key=f"generation-test:{new_id()}",
                    expires_at=None,
                    ref=CreditRef("payment", new_id()),
                ),
            )

    async def set_setting(self, key: str, value: object) -> None:
        resources = self.media.resources
        async with self.database.transaction() as session:
            await session.execute(
                text(
                    "INSERT INTO system_settings (key, value, version) VALUES (:key, CAST(:value AS jsonb), 1) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
                ),
                {"key": key, "value": json.dumps(value)},
            )
        await resources.redis_store.delete(resources.redis_store.keys.key("platform.setting", key))

    async def scalar(self, statement: str, **parameters: Any) -> Any:
        async with self.database.transaction() as session:
            return (await session.execute(text(statement), parameters)).scalar()

    async def row(self, statement: str, **parameters: Any) -> Any:
        async with self.database.transaction() as session:
            return (await session.execute(text(statement), parameters)).first()

    async def wallet(self, user_id: UUID) -> tuple[int, int]:
        found = await self.row("SELECT balance, reserved FROM credit_wallets WHERE user_id = :u", u=user_id)
        return (0, 0) if found is None else (found[0], found[1])

    async def set_status(self, job_id: str | UUID, status: str) -> None:
        async with self.database.transaction() as session:
            await session.execute(
                text("UPDATE jobs SET status = :status WHERE id = :id"), {"status": status, "id": UUID(str(job_id))}
            )

    async def job_count(self, user_id: UUID) -> int:
        return int(await self.scalar("SELECT count(*) FROM jobs WHERE user_id = :u", u=user_id))

    async def job_status(self, job_id: str | UUID) -> str | None:
        return await self.scalar("SELECT status FROM jobs WHERE id = :id", id=UUID(str(job_id)))

    async def seed_job(self, owner: UUID, status: str = "completed", **overrides: Any) -> UUID:
        job_id = new_id()
        values: dict[str, Any] = {
            "id": job_id,
            "user": owner,
            "query": "How does TCP work?",
            "options": json.dumps(job_options(voice_id=self.voice_id).model_dump(mode="json", by_alias=True)),
            "status": status,
            "completed_at": NOW if status in TERMINAL else None,
            "error_code": "tts_failed" if status == "failed" else None,
            "render_id": None,
            "source": "query",
            "topic_id": None,
            **overrides,
        }
        async with self.database.transaction() as session:
            await session.execute(
                text(
                    "INSERT INTO jobs (id, user_id, source, topic_id, query, options, status, credits_estimated, "
                    "credits_reserved, completed_at, error_code, render_id) VALUES (:id, :user, :source, :topic_id, "
                    ":query, CAST(:options AS jsonb), :status, 140, 140, :completed_at, :error_code, :render_id)"
                ),
                values,
            )
        return job_id

    async def seed_storyboard(self, job_id: UUID, *, approved: bool = False, **content: Any) -> UUID:
        storyboard_id = new_id()
        version = (
            await self.scalar("SELECT coalesce(max(version), 0) + 1 FROM storyboards WHERE job_id = :id", id=job_id)
        ) or 1
        async with self.database.transaction() as session:
            await session.execute(
                text(
                    "INSERT INTO storyboards (id, job_id, version, origin, content, approved_at, approved_by) "
                    "VALUES (:id, :job, :version, 'planner', CAST(:content AS jsonb), :approved_at, :approved_by)"
                ),
                {
                    "id": storyboard_id,
                    "job": job_id,
                    "version": version,
                    "content": json.dumps(storyboard_content(**content)),
                    "approved_at": NOW if approved else None,
                    "approved_by": self.primary_id if approved else None,
                },
            )
        return storyboard_id

    async def seed_topic(self, *, active: bool = True) -> UUID:
        category_id, subcategory_id, topic_id = new_id(), new_id(), new_id()
        suffix = topic_id.hex[:10]
        async with self.database.transaction() as session:
            await session.execute(
                text(
                    "INSERT INTO categories (id, parent_id, level, slug, name, is_active) "
                    "VALUES (:id, NULL, 'category', :slug, 'Backend', true)"
                ),
                {"id": category_id, "slug": f"cat-{suffix}"},
            )
            await session.execute(
                text(
                    "INSERT INTO categories (id, parent_id, level, slug, name, is_active) "
                    "VALUES (:id, :parent, 'subcategory', :slug, 'Networking', true)"
                ),
                {"id": subcategory_id, "parent": category_id, "slug": f"sub-{suffix}"},
            )
            await session.execute(
                text(
                    "INSERT INTO topics (id, category_id, slug, title, is_active) "
                    "VALUES (:id, :category, :slug, 'How DNS works', :active)"
                ),
                {"id": topic_id, "category": subcategory_id, "slug": f"topic-{suffix}", "active": active},
            )
        return topic_id

    def body(self, **options: Any) -> dict[str, Any]:
        return {"query": "How does TCP work?", "options": {"durationSeconds": 60, **options}}

    async def create(
        self, client: AsyncClient | None = None, *, key: str | None = None, body: dict[str, Any] | None = None
    ) -> Response:
        caller = client or self.primary
        return await caller.post(
            JOBS,
            json=body or self.body(),
            headers={**csrf(caller), "Idempotency-Key": key or f"job-{new_id()}"},
        )

    async def post(
        self, client: AsyncClient, path: str, body: dict[str, Any] | None = None, *, key: bool = False
    ) -> Response:
        headers = {**csrf(client), **({"Idempotency-Key": f"job-{new_id()}"} if key else {})}
        return await client.post(path, json=body or {}, headers=headers)


async def install_generation_data(api: MediaApi) -> UUID:
    style_id, version_id, voice_id = new_id(), new_id(), new_id()
    async with api.database.transaction() as session:
        await session.execute(
            text(
                "INSERT INTO skills (id, owner_user_id, slug, name, description, visibility, status) "
                "VALUES (:id, NULL, :slug, 'Minimal dark', 'The default look', 'system', 'active')"
            ),
            {"id": style_id, "slug": STYLE},
        )
        await session.execute(
            text(
                "INSERT INTO skill_versions (id, skill_id, version, body_md, frontmatter, checksum, scan_status, "
                "scanned_at) VALUES (:id, :skill, 1, 'body', CAST(:frontmatter AS jsonb), :checksum, 'passed', now())"
            ),
            {
                "id": version_id,
                "skill": style_id,
                "frontmatter": json.dumps({"name": STYLE, "metadata": {"layer": "style", "tokens": ""}}),
                "checksum": bytes(32),
            },
        )
        await session.execute(
            text("UPDATE skills SET current_version_id = :version WHERE id = :id"),
            {"version": version_id, "id": style_id},
        )
        await session.execute(
            text(
                "INSERT INTO voices (id, owner_user_id, provider, provider_voice_id, name, kind, language, status) "
                "VALUES (:id, NULL, 'fake', :provider_voice, 'Aria', 'builtin', 'en', 'ready')"
            ),
            {"id": voice_id, "provider_voice": f"fake-{voice_id.hex[:8]}"},
        )
    return voice_id


def build_generation_service(api: MediaApi, dispatch: RecordingDispatch, guard: FakeEditGuard) -> GenerationService:
    resources = api.resources
    runtime = RuntimeSettings(PlatformSettingsReader(resources.redis_store))
    return GenerationService(
        GenerationDeps(
            credits=CreditsService(resources.clock, resources.settings.billing),
            settings=runtime,
            options=OptionResolver(
                runtime,
                SqlPreferencesLookup(),
                SkillsStyleLookup(),
                VoiceCatalogChoices(VoiceLookupImpl()),
                music_service_for(resources),
            ),
            topics=CatalogTopicLookup(),
            edit_guard=guard,
            renders=media_service_for(resources),
            checkpoints=PostgresCheckpointPurger(resources.settings),
            clock=resources.clock,
            events=resources.events,
            dispatch=JobDispatch(run=dispatch.run, resume=dispatch.resume),
        )
    )


async def purge_generation_data(database: Database) -> None:
    async with database.transaction() as session:
        await session.execute(text("SET LOCAL motionile.allow_purge = 'on'"))
        await session.execute(text("DELETE FROM jobs"))
        await session.execute(text("DELETE FROM user_preferences"))
        await session.execute(text("DELETE FROM voices"))
        await session.execute(text("DELETE FROM skills"))
        await session.execute(text("DELETE FROM topics"))
        await session.execute(text("DELETE FROM categories WHERE level = 'subcategory'"))
        await session.execute(text("DELETE FROM categories"))
        await session.execute(text("DELETE FROM system_settings WHERE key LIKE 'jobs.%'"))
        await session.execute(text("DELETE FROM audit_log WHERE action LIKE 'job.%'"))
    await purge_credit_data(database, [])
