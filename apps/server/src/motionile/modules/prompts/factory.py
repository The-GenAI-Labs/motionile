from motionile.core.resources import Resources
from motionile.modules.prompts.gate import ActivationGate
from motionile.modules.prompts.repository import SqlPromptRepository
from motionile.modules.prompts.seed import PromptSeeder
from motionile.modules.prompts.service import PromptsService
from motionile.modules.prompts.store import DatabasePromptStore


def build_prompts_service(resources: Resources) -> PromptsService:
    return PromptsService(
        transaction=resources.database.transaction,
        store_factory=SqlPromptRepository,
        gate=ActivationGate(SqlPromptRepository),
    )


def build_prompt_seeder(resources: Resources) -> PromptSeeder:
    return PromptSeeder(resources.database.transaction, SqlPromptRepository)


def build_prompt_store(resources: Resources) -> DatabasePromptStore:
    return DatabasePromptStore(resources.database.transaction)
