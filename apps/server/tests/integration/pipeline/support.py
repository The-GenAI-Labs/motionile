import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel
from sqlalchemy import text
from tests.integration.generation_support import GenerationApi

from motionile.core.config import Settings
from motionile.core.db import Database
from motionile.core.ids import new_id
from motionile.core.resources import Resources
from motionile.engine.ai.graphs.deps import PipelineDependencies
from motionile.engine.ai.llm.factory import FakeLlmConfig, build_llm_client
from motionile.engine.ai.llm.fake import FakeScript
from motionile.engine.ai.llm.models import LlmCall, LlmClient, LlmResult, LlmTask
from motionile.engine.ai.ports import JobSnapshot, NarrationScript, RenderProgress
from motionile.engine.ai.prompts import load_prompt_sources
from motionile.engine.ai.skills import load_library
from motionile.modules.generation import ai_fixtures_directory, settings_read_for, usage_ledger_for
from motionile.modules.generation.ai_wiring import SettingsBudgetProvider, SettingsRoutingProvider
from motionile.modules.generation.check_gateway import StorageCheckGateway
from motionile.modules.generation.pipeline_deps import build_dependencies
from motionile.modules.generation.render_gateway import MediaRenderGateway
from motionile.modules.generation.render_queue_checker import RenderQueueChecker
from motionile.modules.generation.runner_impl import GraphPipelineRunner, postgres_checkpointer
from motionile.modules.media import (
    CompositionCheckService,
    MediaService,
    RenderPipeline,
    assets_for,
    delivery_for,
    render_commands_for,
    render_events_for,
)
from motionile.modules.media.check_browser import check_browser_opener
from motionile.modules.prompts import build_prompt_seeder
from motionile.modules.skills import build_skill_seeder
from motionile.modules.voices import VoiceLookupImpl

CHECK_TIMEOUT_SECONDS = 300.0
CHECK_POLL_SECONDS = 0.05
SHORT_VIDEO_SECONDS = 30


@dataclass(frozen=True)
class SseFrame:
    identifier: str | None
    event: str
    data: str


def parse_sse(body: str) -> list[SseFrame]:
    frames: list[SseFrame] = []
    for block in body.split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.split("\n"):
            if line.startswith(":") or ": " not in line:
                continue
            name, value = line.split(": ", 1)
            fields[name] = value
        if "event" in fields:
            frames.append(SseFrame(fields.get("id"), fields["event"], fields.get("data", "")))
    return frames


type Hook = Callable[[], Awaitable[None]]


class HookedLlm:
    def __init__(self, inner: LlmClient, before: dict[LlmTask, Hook], calls: list[LlmTask]) -> None:
        self.inner = inner
        self.before = before
        self.calls = calls

    async def generate[OutputT: BaseModel](self, call: LlmCall, output: type[OutputT]) -> LlmResult[OutputT]:
        self.calls.append(call.task)
        hook = self.before.pop(call.task, None)
        if hook is not None:
            await hook()
        return await self.inner.generate(call, output)


class InlineRenders:
    def __init__(self, inner: MediaRenderGateway, pipeline: RenderPipeline) -> None:
        self._inner = inner
        self._pipeline = pipeline

    async def start(self, job: JobSnapshot, html: str, scenes: list[NarrationScript]) -> UUID:
        render_id = await self._inner.start(job, html, scenes)
        await self._pipeline.run(render_id)
        return render_id

    def follow(self, render_id: UUID) -> AsyncIterator[RenderProgress]:
        return self._inner.follow(render_id)

    async def cancel(self, render_id: UUID) -> None:
        await self._inner.cancel(render_id)


@dataclass
class PipelineEnv:
    generation: GenerationApi
    settings: Settings
    pipeline: RenderPipeline
    script: FakeScript | None = None
    before: dict[LlmTask, Hook] = field(default_factory=dict[LlmTask, Hook])
    llm_calls: list[LlmTask] = field(default_factory=list[LlmTask])
    dispatched_renders: list[UUID] = field(default_factory=list[UUID])

    @property
    def resources(self) -> Resources:
        return self.generation.media.resources

    def scripted_llm(self, resources: Resources) -> LlmClient:
        read = settings_read_for(resources)
        inner = build_llm_client(
            use_fake=True,
            routing=SettingsRoutingProvider(read),
            ledger=usage_ledger_for(resources),
            budget=SettingsBudgetProvider(read),
            fake=FakeLlmConfig(
                fixtures_root=ai_fixtures_directory(resources.settings), script=self.script or FakeScript()
            ),
        )
        return HookedLlm(inner, self.before, self.llm_calls)

    def media_service(self) -> MediaService:
        resources = self.resources
        return MediaService(
            delivery_for(resources),
            commands=render_commands_for(
                resources, lambda _session, render_id: self.dispatched_renders.append(render_id)
            ),
            assets=assets_for(resources),
        )

    async def run_check(self, job_id: UUID, check_id: str) -> None:
        service = CompositionCheckService(
            self.resources.storage, check_browser_opener(self.settings), timeout_seconds=CHECK_TIMEOUT_SECONDS
        )
        await service.run(job_id, check_id)

    async def build(self, resources: Resources, job_id: UUID) -> PipelineDependencies:
        deps = await build_dependencies(resources, job_id)
        gateway = StorageCheckGateway(
            resources.storage, self.run_check, timeout_seconds=CHECK_TIMEOUT_SECONDS, poll_seconds=CHECK_POLL_SECONDS
        )
        renders = MediaRenderGateway(
            resources.database.transaction,
            self.media_service(),
            render_events_for(resources),
            VoiceLookupImpl(),
            default_fps=self.settings.render.fps,
        )
        return replace(deps, checker=RenderQueueChecker(job_id, gateway), renders=InlineRenders(renders, self.pipeline))

    @asynccontextmanager
    async def open_resources(self) -> AsyncGenerator[Resources]:
        yield self.resources

    def runner(self) -> GraphPipelineRunner:
        return GraphPipelineRunner(self.open_resources, postgres_checkpointer, self.build)

    async def fund(self, amount: int = 1_000) -> None:
        await self.generation.fund(self.generation.primary_id, amount)

    async def start(self, **options: Any) -> UUID:
        response = await self.generation.create(
            body=self.generation.body(durationSeconds=SHORT_VIDEO_SECONDS, **options)
        )
        assert response.status_code == 202, response.text
        return UUID(response.json()["id"])

    async def run_to_end(self, **options: Any) -> UUID:
        job_id = await self.start(**options)
        await self.runner().run(job_id)
        return job_id

    async def job(self, job_id: UUID, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
        response = await (client or self.generation.primary).get(f"/v1/jobs/{job_id}")
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    async def event_types(self, job_id: UUID) -> list[str]:
        async with self.generation.database.transaction() as session:
            rows = await session.execute(
                text("SELECT type FROM job_events WHERE job_id = :job ORDER BY id"), {"job": job_id}
            )
            return [row[0] for row in rows]

    async def usage_rows(self, job_id: UUID, stage: str) -> int:
        return int(
            await self.generation.scalar(
                "SELECT count(*) FROM usage_records WHERE job_id = :job AND stage = :stage", job=job_id, stage=stage
            )
        )

    async def cancel(self, job_id: UUID) -> None:
        response = await self.generation.post(self.generation.primary, f"/v1/jobs/{job_id}/cancel")
        assert response.status_code == 202, response.text


async def install_voice(database: Database) -> UUID:
    voice_id = new_id()
    async with database.transaction() as session:
        await session.execute(
            text(
                "INSERT INTO voices (id, owner_user_id, provider, provider_voice_id, name, kind, language, status) "
                "VALUES (:id, NULL, 'fake', :provider_voice, 'Aria', 'builtin', 'en', 'ready')"
            ),
            {"id": voice_id, "provider_voice": f"fake-{voice_id.hex[-12:]}"},
        )
    return voice_id


async def seed_catalogs(resources: Resources) -> None:
    prompts = build_prompt_seeder(resources)
    await prompts.sync(await asyncio.to_thread(load_prompt_sources))
    await prompts.bootstrap(resources.settings.app)
    await build_skill_seeder(resources).sync(await asyncio.to_thread(load_library))


async def purge_pipeline_data(api: GenerationApi) -> None:
    async with api.database.transaction() as session:
        await session.execute(text("SET LOCAL motionile.allow_purge = 'on'"))
        await session.execute(
            text("TRUNCATE langgraph.checkpoint_writes, langgraph.checkpoint_blobs, langgraph.checkpoints")
        )
        await session.execute(text("DELETE FROM share_links"))
        await session.execute(text("DELETE FROM usage_records"))
        await session.execute(text("DELETE FROM skill_embeddings"))
        await session.execute(text("DELETE FROM skill_files"))
        await session.execute(text("UPDATE skills SET current_version_id = NULL"))
        await session.execute(text("DELETE FROM skill_versions"))
