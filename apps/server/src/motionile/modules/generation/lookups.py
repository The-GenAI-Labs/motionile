from contextlib import suppress
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.modules.catalog import TopicBrief, published_topic
from motionile.modules.generation.ports import ChosenVoice, UserPreferences
from motionile.modules.media import VoiceLookup
from motionile.modules.skills import Skill, SkillVersion
from motionile.modules.users import UserPreference
from motionile.modules.voices import Voice, VoiceKind, VoiceNotAvailableError, VoiceStatus

STYLE_LAYER = "style"
SYSTEM_VISIBILITY = "system"
ACTIVE_STATUS = "active"


class SqlPreferencesLookup:
    async def for_user(self, session: AsyncSession, user_id: UUID) -> UserPreferences:
        statement = select(UserPreference).where(UserPreference.user_id == user_id)
        row = await session.scalar(statement.execution_options(populate_existing=True))
        if row is None:
            return UserPreferences()
        return UserPreferences(
            default_style=row.default_style,
            language=row.language,
            default_voice_id=row.default_voice_id,
            default_aspect=row.default_aspect,
            captions_enabled=row.captions_enabled,
        )


class CatalogTopicLookup:
    async def published(self, session: AsyncSession, topic_id: UUID) -> TopicBrief | None:
        return await published_topic(session, topic_id)


class SkillsStyleLookup:
    async def style_exists(self, session: AsyncSession, slug: str) -> bool:
        statement = (
            select(Skill.id)
            .join(SkillVersion, SkillVersion.id == Skill.current_version_id)
            .where(
                Skill.slug == slug,
                Skill.visibility == SYSTEM_VISIBILITY,
                Skill.status == ACTIVE_STATUS,
                Skill.is_enabled.is_(True),
                Skill.deleted_at.is_(None),
                func.jsonb_extract_path_text(SkillVersion.frontmatter, "metadata", "layer") == STYLE_LAYER,
            )
            .limit(1)
        )
        return await session.scalar(statement) is not None


class VoiceCatalogChoices:
    def __init__(self, lookup: VoiceLookup) -> None:
        self._lookup = lookup

    async def choose(self, session: AsyncSession, user_id: UUID, voice_id: UUID) -> ChosenVoice:
        await self._lookup.resolve_selectable(session, user_id, voice_id)
        kind = await session.scalar(select(Voice.kind).where(Voice.id == voice_id))
        return ChosenVoice(voice_id=voice_id, is_cloned=kind == VoiceKind.CLONED.value)

    async def default_for(
        self, session: AsyncSession, user_id: UUID, preferred: UUID | None, language: str
    ) -> ChosenVoice:
        if preferred is not None:
            with suppress(VoiceNotAvailableError):
                return await self.choose(session, user_id, preferred)
        base = language.split("-", maxsplit=1)[0]
        statement = (
            select(Voice.id)
            .where(
                Voice.kind == VoiceKind.BUILTIN.value,
                Voice.status == VoiceStatus.READY.value,
                Voice.provider_voice_id.is_not(None),
                or_(
                    Voice.language == language,
                    Voice.language.startswith(f"{base}-", autoescape=True),
                    Voice.language == base,
                ),
            )
            .order_by((Voice.language == language).desc(), Voice.created_at, Voice.id)
            .limit(1)
        )
        found = await session.scalar(statement)
        if found is None:
            raise VoiceNotAvailableError
        return ChosenVoice(voice_id=found, is_cloned=False)
