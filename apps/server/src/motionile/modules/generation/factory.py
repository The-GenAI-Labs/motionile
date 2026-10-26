from pathlib import Path

from motionile.core.config import Settings
from motionile.core.resources import Resources
from motionile.engine.ai.guardrails import ActivePromptSource, InputGuard
from motionile.engine.ai.llm.config import LlmClientConfig, ProviderKeys
from motionile.engine.ai.llm.embeddings import EmbedderConfig, FakeEmbedder, LiteLlmEmbedder
from motionile.engine.ai.llm.factory import FakeLlmConfig, build_llm_client
from motionile.engine.ai.llm.models import Embedder, LlmClient, Tracer, UsageLedger
from motionile.engine.ai.llm.tracing import LangfuseConfig, LangfuseTracer, NoopTracer, create_langfuse_client
from motionile.engine.ai.ports import PromptStore
from motionile.modules.credits import CreditsService
from motionile.modules.generation.ai_wiring import (
    InputGuardEditGuard,
    RecordedUsageLedger,
    SettingRead,
    SettingsBudgetProvider,
    SettingsRoutingProvider,
)
from motionile.modules.generation.job_events import JobEvents
from motionile.modules.generation.lookups import (
    CatalogTopicLookup,
    SkillsStyleLookup,
    SqlPreferencesLookup,
    VoiceCatalogChoices,
)
from motionile.modules.generation.options import OptionResolver
from motionile.modules.generation.pipeline_repository import PublishingJobRepository
from motionile.modules.generation.ports import EditGuard
from motionile.modules.generation.runtime_settings import PlatformSettingsReader, RuntimeSettings
from motionile.modules.generation.service import GenerationDeps, GenerationService
from motionile.modules.generation.tasks import DISPATCH
from motionile.modules.media import media_service_for, music_service_for
from motionile.modules.platform import SettingValue
from motionile.modules.voices import VoiceLookupImpl

SERVER_ROOT = Path(__file__).resolve().parents[4]
FIXTURES_RELATIVE = Path("tests") / "fixtures" / "llm"
SERVICE_KEY = "generation.service"
LEDGER_KEY = "generation.usage_ledger"
LLM_KEY = "generation.llm"
TRACER_KEY = "generation.tracer"
PROMPTS_KEY = "generation.prompts"
EMBEDDER_KEY = "generation.embedder"
EDIT_GUARD_KEY = "generation.edit_guard"
JOB_EVENTS_KEY = "generation.job_events"


def ai_fixtures_directory(settings: Settings) -> Path:
    return settings.ai.fixtures_directory or SERVER_ROOT / FIXTURES_RELATIVE


def settings_read_for(resources: Resources) -> SettingRead:
    reader = PlatformSettingsReader(resources.redis_store)

    async def read(key: str) -> SettingValue:
        async with resources.database.session() as session:
            return await reader.value(session, key)

    return read


def tracer_for(resources: Resources) -> Tracer:
    def build() -> Tracer:
        ai = resources.settings.ai
        if ai.langfuse_public_key is None or ai.langfuse_secret_key is None:
            return NoopTracer()
        return LangfuseTracer(
            create_langfuse_client(
                LangfuseConfig(
                    public_key=ai.langfuse_public_key,
                    secret_key=ai.langfuse_secret_key,
                    host=ai.langfuse_host,
                    environment=resources.settings.app.env.value,
                )
            )
        )

    return resources.shared_instance(TRACER_KEY, build)


def usage_ledger_for(resources: Resources) -> UsageLedger:
    return resources.shared_instance(LEDGER_KEY, lambda: RecordedUsageLedger(resources.database.transaction))


def llm_client_for(resources: Resources) -> LlmClient:
    def build() -> LlmClient:
        settings = resources.settings
        read = settings_read_for(resources)
        use_fake = settings.is_fake_providers
        return build_llm_client(
            use_fake=use_fake,
            routing=SettingsRoutingProvider(read),
            ledger=usage_ledger_for(resources),
            budget=SettingsBudgetProvider(read),
            tracer=tracer_for(resources),
            config=LlmClientConfig(
                keys=ProviderKeys(anthropic=settings.ai.anthropic_api_key, openai=settings.openai.api_key)
            ),
            fake=FakeLlmConfig(fixtures_root=ai_fixtures_directory(settings)) if use_fake else None,
        )

    return resources.shared_instance(LLM_KEY, build)


def embedder_for(resources: Resources) -> Embedder:
    def build() -> Embedder:
        settings = resources.settings
        ai = settings.ai
        if settings.is_fake_providers:
            return FakeEmbedder(dimensions=ai.embedding_dimensions, ledger=usage_ledger_for(resources))
        keys = ProviderKeys(anthropic=ai.anthropic_api_key, openai=settings.openai.api_key)
        config = EmbedderConfig.with_keys(ai.embedding_model, ai.embedding_dimensions, keys)
        return LiteLlmEmbedder(config, usage_ledger_for(resources))

    return resources.shared_instance(EMBEDDER_KEY, build)


def prompt_store_for(resources: Resources) -> PromptStore:
    def build() -> PromptStore:
        from motionile.modules.prompts import build_prompt_store  # noqa: PLC0415

        return build_prompt_store(resources)

    return resources.shared_instance(PROMPTS_KEY, build)


def edit_guard_for(
    resources: Resources, *, llm: LlmClient | None = None, prompts: ActivePromptSource | None = None
) -> EditGuard:
    def build() -> EditGuard:
        return InputGuardEditGuard(InputGuard(llm or llm_client_for(resources), prompts or prompt_store_for(resources)))

    if llm is not None or prompts is not None:
        return build()
    return resources.shared_instance(EDIT_GUARD_KEY, build)


def job_events_for(resources: Resources) -> JobEvents:
    return resources.shared_instance(JOB_EVENTS_KEY, lambda: JobEvents(resources.redis_store))


def generation_service_for(resources: Resources) -> GenerationService:
    def build() -> GenerationService:
        events = job_events_for(resources)
        settings = RuntimeSettings(PlatformSettingsReader(resources.redis_store))
        return GenerationService(
            GenerationDeps(
                credits=CreditsService(resources.clock, resources.settings.billing),
                settings=settings,
                options=OptionResolver(
                    settings,
                    SqlPreferencesLookup(),
                    SkillsStyleLookup(),
                    VoiceCatalogChoices(VoiceLookupImpl()),
                    music_service_for(resources),
                ),
                topics=CatalogTopicLookup(),
                edit_guard=edit_guard_for(resources),
                renders=media_service_for(resources),
                clock=resources.clock,
                events=resources.events,
                dispatch=DISPATCH,
                store_factory=lambda session: PublishingJobRepository(session, events),
            )
        )

    return resources.shared_instance(SERVICE_KEY, build)
