from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.resources import Resources
from motionile.engine.ai.graphs.deps import PipelineConfig, PipelineDependencies
from motionile.engine.ai.graphs.errors import PipelineError
from motionile.engine.ai.guardrails import InputGuard, OutputGuard
from motionile.engine.ai.ports import ActivePrompt, PromptStore
from motionile.engine.ai.prompts.canary import OutputScanner
from motionile.engine.ai.skills import LibrarySkillRouter
from motionile.modules.generation.check_gateway import StorageCheckGateway
from motionile.modules.generation.factory import (
    embedder_for,
    generation_service_for,
    job_events_for,
    llm_client_for,
    prompt_store_for,
)
from motionile.modules.generation.narrator import MediaNarrator
from motionile.modules.generation.pipeline_store import SqlPipelineStore
from motionile.modules.generation.render_gateway import MediaRenderGateway
from motionile.modules.generation.render_queue_checker import RenderQueueChecker
from motionile.modules.generation.runtime_settings import PlatformSettingsReader, RuntimeSettings
from motionile.modules.media import defer_composition_check, media_service_for, render_events_for
from motionile.modules.prompts import PromptNotActiveError
from motionile.modules.skills import build_skill_catalog
from motionile.modules.voices import VoiceLookupImpl

SECONDS_PER_MINUTE: Final = 60
PROMPT_NOT_ACTIVE: Final = "prompt_not_active"


class PipelinePromptStore:
    def __init__(self, inner: PromptStore) -> None:
        self._inner = inner

    async def active(self, key: str) -> ActivePrompt:
        try:
            return await self._inner.active(key)
        except PromptNotActiveError as error:
            raise PipelineError(
                PROMPT_NOT_ACTIVE, "The video service is not ready yet. Please try again later."
            ) from error

    async def all_active(self) -> list[ActivePrompt]:
        return await self._inner.all_active()


async def pipeline_config(session: AsyncSession, resources: Resources) -> PipelineConfig:
    reader = PlatformSettingsReader(resources.redis_store)
    runtime = RuntimeSettings(reader)
    review_enabled = await reader.value(session, "ai.visual_review_enabled")
    stage_timeout = await runtime.stage_timeout(session)
    return PipelineConfig(
        max_repairs=await runtime.integer(session, "ai.max_repairs"),
        scene_concurrency=await runtime.integer(session, "ai.scene_concurrency"),
        skill_token_budget=await runtime.integer(session, "ai.skill_token_budget"),
        limits=await runtime.storyboard_limits(session),
        visual_review_enabled=review_enabled is True,
        render_timeout_seconds=stage_timeout.total_seconds(),
        approval_timeout_hours=await runtime.integer(session, "ai.approval_timeout_hours"),
        max_duration_ms=resources.settings.render.max_duration_ms,
    )


async def build_dependencies(resources: Resources, job_id: UUID) -> PipelineDependencies:
    settings = resources.settings
    transaction = resources.database.transaction
    llm = llm_client_for(resources)
    prompts = PipelinePromptStore(prompt_store_for(resources))
    media = media_service_for(resources)
    voices = VoiceLookupImpl()
    async with transaction() as session:
        config = await pipeline_config(session, resources)
    gateway = StorageCheckGateway(
        resources.storage,
        defer_composition_check,
        timeout_seconds=float(config.render_timeout_seconds),
    )
    return PipelineDependencies(
        store=SqlPipelineStore(
            transaction, generation_service_for(resources), job_events_for(resources), resources.clock
        ),
        narrator=MediaNarrator(transaction, resources.database.session, media, voices),
        checker=RenderQueueChecker(job_id, gateway),
        renders=MediaRenderGateway(
            transaction, media, render_events_for(resources), voices, default_fps=settings.render.fps
        ),
        prompts=prompts,
        skill_router=LibrarySkillRouter(build_skill_catalog(resources), embedder_for(resources), llm, prompts),
        catalog=build_skill_catalog(resources),
        llm=llm,
        input_guard=InputGuard(llm, prompts),
        output_guard=OutputGuard(llm, prompts, OutputScanner(await prompts.all_active(), ())),
        config=config,
    )
