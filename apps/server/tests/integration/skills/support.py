from dataclasses import dataclass
from typing import Any
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.media_support import MediaApi

from motionile.core.db import Database

ADMIN = "/v1/admin/skills"
DELETE_STATEMENTS = (
    "DELETE FROM skills WHERE visibility = 'system'",
    "DELETE FROM audit_log WHERE action LIKE 'skills.%'",
)


@dataclass
class SkillsApi:
    media: MediaApi

    @property
    def database(self) -> Database:
        return self.media.database

    @property
    def curator(self) -> AsyncClient:
        return self.media.other

    @property
    def curator_id(self) -> UUID:
        return self.media.other_id

    async def scalar(self, statement: str, **parameters: Any) -> Any:
        async with self.database.transaction() as session:
            return (await session.execute(text(statement), parameters)).scalar()

    async def rows(self, statement: str, **parameters: Any) -> list[Any]:
        async with self.database.transaction() as session:
            return list((await session.execute(text(statement), parameters)).all())

    async def execute(self, statement: str, **parameters: Any) -> None:
        async with self.database.transaction() as session:
            await session.execute(text(statement), parameters)


async def purge_skills(database: Database) -> None:
    async with database.transaction() as session:
        await session.execute(text("SET LOCAL motionile.allow_purge = 'on'"))
        for statement in DELETE_STATEMENTS:
            await session.execute(text(statement))
