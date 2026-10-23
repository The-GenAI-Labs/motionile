from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

import pytest
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from tests.fakes.resources import make_resources
from tests.fakes.settings import make_settings

from motionile.core.config import ProvidersMode
from motionile.core.ids import new_id
from motionile.core.redis import RedisStore
from motionile.core.resources import Resources
from motionile.core.security.rbac import Principal, PrincipalKind
from motionile.entrypoints import api
from motionile.modules.auth import enforce_csrf
from motionile.modules.auth.dependencies import current_principal
from motionile.modules.media import FakeConsentTranscripts
from motionile.scripts.export_openapi import render_openapi

PATH = "/v1/_test/voices/consent-transcript"
SENTENCE = "I agree that Motionile may create a synthetic copy of my voice"


@dataclass
class Harness:
    application: FastAPI
    resources: Resources
    transcripts: FakeConsentTranscripts
    caller: list[Principal]

    def sign_in(self, user_id: UUID | None) -> None:
        self.caller[:] = [Principal(PrincipalKind.USER, user_id=user_id)]

    def client(self) -> AsyncClient:
        return AsyncClient(transport=ASGITransport(app=self.application), base_url="http://test")


async def harness_for(providers_mode: ProvidersMode) -> AsyncIterator[Harness]:
    settings = make_settings(providers_mode=providers_mode)
    resources = make_resources(settings)
    await resources.redis.aclose()
    redis = FakeRedis()
    resources.redis = redis
    resources.redis_store = RedisStore(redis, resources.redis_store.keys)
    application = api.create_app(settings, resources=resources)
    caller: list[Principal] = [Principal(PrincipalKind.USER, user_id=new_id())]

    async def principal() -> Principal:
        return caller[0]

    async def csrf_passes() -> None:
        return None

    application.dependency_overrides[current_principal] = principal
    application.dependency_overrides[enforce_csrf] = csrf_passes
    yield Harness(application, resources, FakeConsentTranscripts(resources.redis_store), caller)
    await resources.aclose()


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    async for built in harness_for(ProvidersMode.FAKE):
        yield built


@pytest.fixture
async def live_harness() -> AsyncIterator[Harness]:
    async for built in harness_for(ProvidersMode.LIVE):
        yield built


def caller_id(harness: Harness) -> UUID:
    user_id = harness.caller[0].user_id
    assert user_id is not None
    return user_id


async def test_the_caller_can_store_the_text_the_fake_transcriber_should_return(harness: Harness) -> None:
    async with harness.client() as client:
        response = await client.post(PATH, json={"text": SENTENCE})

    assert response.status_code == 204
    assert await harness.transcripts.get(caller_id(harness)) == SENTENCE


async def test_the_stored_text_is_scoped_to_the_calling_user(harness: Harness) -> None:
    first = caller_id(harness)
    async with harness.client() as client:
        await client.post(PATH, json={"text": SENTENCE})
        harness.sign_in(new_id())
        await client.post(PATH, json={"text": "another sentence entirely"})

    assert await harness.transcripts.get(first) == SENTENCE
    assert await harness.transcripts.get(caller_id(harness)) == "another sentence entirely"


async def test_the_stored_text_expires_on_its_own(harness: Harness) -> None:
    async with harness.client() as client:
        await client.post(PATH, json={"text": SENTENCE})

    key = harness.resources.redis_store.keys.key("media.fake_consent_transcript", caller_id(harness))
    assert 0 < await harness.resources.redis.pttl(key) <= 15 * 60 * 1000


async def test_the_caller_can_clear_the_stored_text(harness: Harness) -> None:
    async with harness.client() as client:
        await client.post(PATH, json={"text": SENTENCE})
        response = await client.delete(PATH)

    assert response.status_code == 204
    assert await harness.transcripts.get(caller_id(harness)) is None


async def test_clearing_one_user_leaves_the_text_of_another_in_place(harness: Harness) -> None:
    other = new_id()
    await harness.transcripts.put(other, SENTENCE)
    async with harness.client() as client:
        await client.delete(PATH)

    assert await harness.transcripts.get(other) == SENTENCE


@pytest.mark.parametrize("body", [{}, {"text": ""}, {"text": "x" * 1001}, {"text": SENTENCE, "extra": 1}])
async def test_an_invalid_body_is_rejected(harness: Harness, body: dict[str, object]) -> None:
    async with harness.client() as client:
        response = await client.post(PATH, json=body)

    assert response.status_code == 422
    assert await harness.transcripts.get(caller_id(harness)) is None


async def test_a_principal_without_a_user_is_rejected(harness: Harness) -> None:
    harness.sign_in(None)
    async with harness.client() as client:
        response = await client.post(PATH, json={"text": SENTENCE})

    assert response.status_code == 401


async def test_the_routes_answer_not_found_when_providers_are_live(live_harness: Harness) -> None:
    async with live_harness.client() as client:
        stored = await client.post(PATH, json={"text": SENTENCE})
        cleared = await client.delete(PATH)

    assert stored.status_code == 404
    assert cleared.status_code == 404
    assert await live_harness.transcripts.get(caller_id(live_harness)) is None


def test_the_routes_are_absent_from_the_published_contract() -> None:
    assert "consent-transcript" not in render_openapi()


async def test_requests_without_credentials_never_reach_the_store() -> None:
    settings = make_settings()
    resources = make_resources(settings)
    application = api.create_app(settings, resources=resources)
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        response = await client.post(PATH, json={"text": SENTENCE})
    await resources.aclose()

    assert response.status_code in {401, 403}
