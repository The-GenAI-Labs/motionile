from motionile.core.config import Settings
from motionile.core.resources import Resources
from motionile.engine.ai.llm.config import ProviderKeys
from motionile.engine.ai.llm.embeddings import EmbedderConfig, FakeEmbedder, LiteLlmEmbedder
from motionile.engine.ai.llm.models import Embedder
from motionile.modules.skills.catalog import DatabaseSkillCatalog
from motionile.modules.skills.repository import SqlSkillRepository
from motionile.modules.skills.seed import SkillSeeder
from motionile.modules.skills.service import SkillsService
from motionile.modules.skills.usage import LoggedUsageLedger


def build_embedder(settings: Settings) -> Embedder:
    ai = settings.ai
    if settings.is_fake_providers:
        return FakeEmbedder(dimensions=ai.embedding_dimensions)
    keys = ProviderKeys(anthropic=ai.anthropic_api_key, openai=settings.openai.api_key)
    config = EmbedderConfig.with_keys(ai.embedding_model, ai.embedding_dimensions, keys)
    return LiteLlmEmbedder(config, LoggedUsageLedger())


def build_skill_seeder(resources: Resources, embedder: Embedder | None = None) -> SkillSeeder:
    return SkillSeeder(
        resources.database.transaction,
        embedder or build_embedder(resources.settings),
        resources.clock,
        SqlSkillRepository,
    )


def build_skill_catalog(resources: Resources) -> DatabaseSkillCatalog:
    return DatabaseSkillCatalog(resources.database.transaction, SqlSkillRepository)


def build_skills_service(resources: Resources) -> SkillsService:
    embedder = build_embedder(resources.settings)
    return SkillsService(
        transaction=resources.database.transaction,
        store_factory=SqlSkillRepository,
        seeder=build_skill_seeder(resources, embedder),
        embedding_model=embedder.model,
    )
