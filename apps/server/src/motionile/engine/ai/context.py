from collections.abc import Sequence
from typing import Final

import structlog

from motionile.engine.ai.ports import ContextProvider, ContextSection, JobSnapshot

MAX_CONTEXT_CHARS: Final = 6_000
MAX_SECTION_CHARS: Final = 1_500
TOPIC_SECTION_TITLE: Final = "topic"
PREFERENCES_SECTION_TITLE: Final = "preferences"

logger = structlog.get_logger(__name__)


class TopicContextProvider:
    name = TOPIC_SECTION_TITLE

    async def gather(self, job: JobSnapshot) -> ContextSection | None:
        topic = job.topic
        if topic is None:
            return None
        lines = [f"title: {topic.title}", f"category: {topic.category}", f"subcategory: {topic.subcategory}"]
        if topic.description:
            lines.append(f"description: {topic.description}")
        return ContextSection(title=TOPIC_SECTION_TITLE, text="\n".join(lines))


class PreferencesContextProvider:
    name = PREFERENCES_SECTION_TITLE

    async def gather(self, job: JobSnapshot) -> ContextSection | None:
        preferences = job.preferences
        pairs = (("pace", preferences.pace), ("depth", preferences.depth), ("language", preferences.language))
        lines = [f"{key}: {value}" for key, value in pairs if value]
        if not lines:
            return None
        return ContextSection(title=PREFERENCES_SECTION_TITLE, text="\n".join(lines))


def builtin_providers() -> tuple[ContextProvider, ...]:
    return (TopicContextProvider(), PreferencesContextProvider())


async def gather_sections(providers: Sequence[ContextProvider], job: JobSnapshot) -> list[ContextSection]:
    sections: list[ContextSection] = []
    for provider in providers:
        try:
            section = await provider.gather(job)
        except Exception:
            logger.warning("ai.context_provider_failed", provider=provider.name, job_id=str(job.id))
            continue
        if section is not None:
            sections.append(section)
    return sections


def render_sections(sections: Sequence[ContextSection]) -> str:
    rendered = [f"{section.title}:\n{section.text[:MAX_SECTION_CHARS]}" for section in sections if section.text.strip()]
    return "\n".join(rendered)[:MAX_CONTEXT_CHARS]
