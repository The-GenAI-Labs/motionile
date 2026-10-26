from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.redis import RedisStore
from motionile.engine.ai.storyboard import StoryboardLimits
from motionile.modules.generation.charging import ChargingParameters
from motionile.modules.generation.ports import SettingsReader
from motionile.modules.platform import PlatformService, SettingValue

MILLI = 1_000
RESERVATION_MARGIN = timedelta(hours=24)


class PlatformSettingsReader:
    def __init__(self, redis: RedisStore) -> None:
        self._redis = redis

    async def value(self, session: AsyncSession, key: str) -> SettingValue:
        return await PlatformService(session, self._redis).setting_value(key)


def as_integer(key: str, value: SettingValue) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"setting {key} is not an integer")
    return value


def as_strings(key: str, value: SettingValue) -> list[str]:
    if not isinstance(value, list):
        raise TypeError(f"setting {key} is not a list")
    return value


class RuntimeSettings:
    def __init__(self, reader: SettingsReader) -> None:
        self._reader = reader

    async def integer(self, session: AsyncSession, key: str) -> int:
        return as_integer(key, await self._reader.value(session, key))

    async def charging(self, session: AsyncSession) -> ChargingParameters:
        return ChargingParameters(
            base_credits=await self.integer(session, "charging.base_credits"),
            credits_per_second=await self.integer(session, "charging.credits_per_second"),
            extra_aspect_percent=await self.integer(session, "charging.extra_aspect_percent"),
            cloned_voice_premium=await self.integer(session, "charging.cloned_voice_premium"),
        )

    async def max_active_jobs(self, session: AsyncSession) -> int:
        return await self.integer(session, "jobs.max_active_per_user")

    async def languages(self, session: AsyncSession) -> list[str]:
        return as_strings("preferences.languages", await self._reader.value(session, "preferences.languages"))

    async def aspects(self, session: AsyncSession) -> list[str]:
        return as_strings("preferences.aspects", await self._reader.value(session, "preferences.aspects"))

    async def approval_timeout(self, session: AsyncSession) -> timedelta:
        return timedelta(hours=await self.integer(session, "ai.approval_timeout_hours"))

    async def stage_timeout(self, session: AsyncSession) -> timedelta:
        return timedelta(minutes=await self.integer(session, "ai.stage_timeout_minutes"))

    async def reservation_ttl(self, session: AsyncSession) -> timedelta:
        return await self.approval_timeout(session) + RESERVATION_MARGIN

    async def storyboard_limits(self, session: AsyncSession) -> StoryboardLimits:
        minimum = await self.integer(session, "ai.speaking_rate_min_milli_wps")
        maximum = await self.integer(session, "ai.speaking_rate_max_milli_wps")
        return StoryboardLimits(min_words_per_second=minimum / MILLI, max_words_per_second=maximum / MILLI)
