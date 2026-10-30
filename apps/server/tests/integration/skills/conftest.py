from collections.abc import AsyncIterator

import pytest
from tests.integration.media_support import MediaApi
from tests.integration.skills.support import SkillsApi, purge_skills

from motionile.core.db import Database


@pytest.fixture
async def clean_skills(database: Database) -> AsyncIterator[None]:
    await purge_skills(database)
    yield
    await purge_skills(database)


@pytest.fixture
async def skills_api(media_api: MediaApi, clean_skills: None) -> SkillsApi:
    del clean_skills
    api = SkillsApi(media_api)
    await media_api.grant_permissions(media_api.other_id, "skills", "skills.manage")
    return api
