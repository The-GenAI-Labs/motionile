from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.modules.platform.models import FeatureFlag, SystemSetting


class PlatformRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def settings(self) -> list[SystemSetting]:
        return list(await self.session.scalars(select(SystemSetting).order_by(SystemSetting.key)))

    async def setting(self, key: str) -> SystemSetting | None:
        return await self.session.get(SystemSetting, key)

    async def update_setting(self, key: str, value: object, version: int, updated_by: object) -> SystemSetting | None:
        result = await self.session.execute(
            update(SystemSetting)
            .where(SystemSetting.key == key, SystemSetting.version == version)
            .values(value=value, version=SystemSetting.version + 1, updated_by=updated_by)
            .returning(SystemSetting)
        )
        return result.scalar_one_or_none()

    async def flags(self) -> list[FeatureFlag]:
        return list(await self.session.scalars(select(FeatureFlag).order_by(FeatureFlag.key)))

    async def flag(self, key: str, *, lock: bool = False) -> FeatureFlag | None:
        query = select(FeatureFlag).where(FeatureFlag.key == key)
        if lock:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def delete_flag(self, key: str, version: int) -> bool:
        result = await self.session.execute(
            delete(FeatureFlag).where(FeatureFlag.key == key, FeatureFlag.version == version).returning(FeatureFlag.key)
        )
        return result.scalar_one_or_none() is not None
