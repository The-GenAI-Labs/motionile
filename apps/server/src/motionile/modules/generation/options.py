from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.engine.ai.job_options import AspectName, JobOptions, RevisionRequest
from motionile.modules.generation.charging import ChargingParameters, estimate_credits
from motionile.modules.generation.exceptions import (
    AspectNotAllowedError,
    JobOptionsInvalidError,
    LanguageNotSupportedError,
    StyleNotFoundError,
)
from motionile.modules.generation.ports import (
    ChosenVoice,
    MusicCheck,
    PreferencesLookup,
    SkillLookup,
    UserPreferences,
    VoiceChoices,
)
from motionile.modules.generation.runtime_settings import RuntimeSettings
from motionile.modules.generation.schemas import JobOptionsOverrides, JobOptionsRequest

DEFAULT_STYLE = "minimal-dark"
DEFAULT_LANGUAGE = "en"
DEFAULT_ASPECT: AspectName = "16:9"
ASPECT_NAMES: tuple[AspectName, ...] = ("16:9", "9:16", "1:1")


@dataclass(frozen=True, slots=True)
class OptionInputs:
    duration_seconds: int | None = None
    aspects: list[AspectName] | None = None
    style: str | None = None
    voice_id: UUID | None = None
    language: str | None = None
    review_storyboard: bool | None = None
    music_track_id: UUID | None = None
    music_given: bool = False
    subtitles: bool | None = None
    burn_in_subtitles: bool | None = None

    @classmethod
    def from_request(cls, request: JobOptionsRequest) -> "OptionInputs":
        return cls(
            duration_seconds=request.duration_seconds,
            aspects=request.aspects,
            style=request.style,
            voice_id=request.voice_id,
            language=request.language,
            review_storyboard=request.review_storyboard,
            music_track_id=request.music_track_id,
            music_given=True,
            subtitles=request.subtitles,
            burn_in_subtitles=request.burn_in_subtitles,
        )

    @classmethod
    def from_overrides(cls, overrides: JobOptionsOverrides | None) -> "OptionInputs":
        if overrides is None:
            return cls()
        return cls(
            duration_seconds=overrides.duration_seconds,
            aspects=overrides.aspects,
            style=overrides.style,
            voice_id=overrides.voice_id,
            language=overrides.language,
            review_storyboard=overrides.review_storyboard,
            music_track_id=overrides.music_track_id,
            music_given="music_track_id" in overrides.model_fields_set,
            subtitles=overrides.subtitles,
            burn_in_subtitles=overrides.burn_in_subtitles,
        )


def estimate_for(parameters: ChargingParameters, options: JobOptions) -> int:
    return estimate_credits(parameters, options.duration_seconds, len(options.aspects), options.voice_is_cloned)


def aspect_names(values: list[str]) -> list[AspectName]:
    return [name for name in ASPECT_NAMES if name in values]


class OptionResolver:
    def __init__(
        self,
        settings: RuntimeSettings,
        preferences: PreferencesLookup,
        skills: SkillLookup,
        voices: VoiceChoices,
        music: MusicCheck,
    ) -> None:
        self._settings = settings
        self._preferences = preferences
        self._skills = skills
        self._voices = voices
        self._music = music

    async def resolve(
        self, session: AsyncSession, user_id: UUID, inputs: OptionInputs, base: JobOptions | None = None
    ) -> JobOptions:
        preferences = await self._preferences.for_user(session, user_id)
        duration = inputs.duration_seconds if inputs.duration_seconds is not None else base_duration(base)
        language = inputs.language or (base.language if base else preferences.language or DEFAULT_LANGUAGE)
        aspects = inputs.aspects or (base.aspects if base else [default_aspect(preferences)])
        style = inputs.style or (base.style if base else preferences.default_style or DEFAULT_STYLE)
        await self._check_allowed(session, language, aspects)
        if not await self._skills.style_exists(session, style):
            raise StyleNotFoundError
        music = inputs.music_track_id if inputs.music_given or base is None else base.music_track_id
        if music is not None:
            await self._music.require_active(session, music)
        wanted = inputs.voice_id or (base.voice_id if base else None)
        voice = await self._voice(session, user_id, wanted, preferences, language)
        return build_options(
            {
                "duration_seconds": duration,
                "aspects": aspects,
                "style": style,
                "voice_id": voice.voice_id,
                "voice_is_cloned": voice.is_cloned,
                "language": language,
                "review_storyboard": pick(inputs.review_storyboard, base.review_storyboard if base else None, False),
                "music_track_id": music,
                "subtitles": pick(
                    inputs.subtitles,
                    base.subtitles if base else None,
                    True if preferences.captions_enabled is None else preferences.captions_enabled,
                ),
                "burn_in_subtitles": pick(inputs.burn_in_subtitles, base.burn_in_subtitles if base else None, False),
            }
        )

    async def _check_allowed(self, session: AsyncSession, language: str, aspects: list[AspectName]) -> None:
        if language not in await self._settings.languages(session):
            raise LanguageNotSupportedError
        allowed = await self._settings.aspects(session)
        if any(aspect not in allowed for aspect in aspects):
            raise AspectNotAllowedError

    async def _voice(
        self, session: AsyncSession, user_id: UUID, wanted: UUID | None, preferences: UserPreferences, language: str
    ) -> ChosenVoice:
        if wanted is not None:
            return await self._voices.choose(session, user_id, wanted)
        return await self._voices.default_for(session, user_id, preferences.default_voice_id, language)


def pick[ValueT](explicit: ValueT | None, inherited: ValueT | None, fallback: ValueT) -> ValueT:
    if explicit is not None:
        return explicit
    return inherited if inherited is not None else fallback


def base_duration(base: JobOptions | None) -> int:
    if base is None:
        raise JobOptionsInvalidError("The duration is required.")
    return base.duration_seconds


def default_aspect(preferences: UserPreferences) -> AspectName:
    names = aspect_names([preferences.default_aspect] if preferences.default_aspect else [])
    return names[0] if names else DEFAULT_ASPECT


def build_options(values: dict[str, object]) -> JobOptions:
    try:
        return JobOptions.model_validate(values)
    except ValidationError as error:
        raise JobOptionsInvalidError(f"The options are invalid: {error.error_count()} problem(s).") from None


def with_revision(options: JobOptions, revision: RevisionRequest | None) -> JobOptions:
    return options.model_copy(update={"revision": revision})
