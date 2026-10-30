from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from motionile.core.config import AppEnv, AppSettings, ProvidersMode
from motionile.engine.ai.prompts.canary import new_canary
from motionile.engine.ai.prompts.loader import PromptSource
from motionile.modules.prompts.activation import switch_active
from motionile.modules.prompts.auditing import audit
from motionile.modules.prompts.domain import AUDIT_TEMPLATE_TARGET, Activation, ActivationKind, PromptAction, Subject
from motionile.modules.prompts.exceptions import BootstrapRefusedError
from motionile.modules.prompts.repository import NewVersion, SqlPromptRepository, StoreFactory, Transaction

BOOTSTRAP_ENVIRONMENTS: Final = frozenset({AppEnv.LOCAL, AppEnv.CI})
DESCRIPTIONS: Final[Mapping[str, str]] = {
    "guard.input": "Screens queries, storyboard edits and revision instructions before any generation spend",
    "guard.output": "Checks the storyboard and narration against the content policy before narration and rendering",
    "router.skills": "Selects the style, visual and domain skills for a job",
    "planner.storyboard": "Plans the storyboard of a video from a topic or question",
    "critic.storyboard": "Reviews a storyboard for accuracy, pacing and coverage",
    "scene.module": "Writes the scene module of one storyboard scene",
    "repair.scene": "Repairs a scene module that failed validation or review",
    "review.vision": "Reviews rendered key frames of a scene against a rubric",
}


@dataclass(frozen=True, slots=True)
class SeededVersion:
    key: str
    version: int


@dataclass(frozen=True, slots=True)
class SeedReport:
    templates_created: int
    versions_created: tuple[SeededVersion, ...]
    unchanged: int


def bootstrap_allowed(app: AppSettings) -> bool:
    return app.env in BOOTSTRAP_ENVIRONMENTS and app.providers_mode is ProvidersMode.FAKE


def ensure_bootstrap_allowed(app: AppSettings) -> None:
    if not bootstrap_allowed(app):
        raise BootstrapRefusedError(
            "Prompts are activated without evaluation only in local and CI environments with fake providers."
        )


class PromptSeeder:
    def __init__(self, transaction: Transaction, store_factory: StoreFactory = SqlPromptRepository) -> None:
        self._transaction = transaction
        self._store_factory = store_factory

    async def sync(self, sources: Sequence[PromptSource]) -> SeedReport:
        templates_created = 0
        created: list[SeededVersion] = []
        unchanged = 0
        async with self._transaction() as session:
            repository = self._store_factory(session)
            for source in sources:
                _, was_created = await repository.ensure_template(source.key, DESCRIPTIONS.get(source.key))
                templates_created += int(was_created)
                template = await repository.template(source.key, lock=True)
                if template is None:
                    continue
                if await repository.version_by_checksum(template.id, source.checksum) is not None:
                    unchanged += 1
                    continue
                number = await repository.latest_number(template.id) + 1
                version = await repository.insert_version(
                    NewVersion(
                        template_id=template.id,
                        number=number,
                        body=source.body,
                        variables=source.variables,
                        checksum=source.checksum,
                        canary=new_canary(),
                        created_by=None,
                    )
                )
                await audit(
                    session,
                    None,
                    PromptAction.DRAFT_CREATED,
                    Subject(AUDIT_TEMPLATE_TARGET, template.id),
                    {"key": source.key, "version": number, "version_id": str(version.id), "source": "seed"},
                )
                created.append(SeededVersion(source.key, number))
        return SeedReport(templates_created, tuple(created), unchanged)

    async def bootstrap(self, app: AppSettings) -> tuple[str, ...]:
        ensure_bootstrap_allowed(app)
        activated: list[str] = []
        async with self._transaction() as session:
            repository = self._store_factory(session)
            for summary in await repository.summaries():
                template = await repository.template(summary.key, lock=True)
                latest = await repository.latest_version(template.id) if template is not None else None
                if template is None or latest is None or template.active_version_id == latest.id:
                    continue
                await switch_active(
                    session,
                    repository,
                    template,
                    latest,
                    Activation(ActivationKind.ACTIVATED, None, {"bootstrap": True}),
                )
                activated.append(template.key)
        return tuple(activated)
