from dataclasses import dataclass, field
from datetime import timedelta
from typing import Annotated
from uuid import UUID

import httpx
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from tests.fakes.resources import FIXED_NOW
from tests.fakes.settings import make_settings

from motionile.core.clock import FrozenClock
from motionile.core.db import Database, create_engine
from motionile.core.errors import register_exception_handlers
from motionile.core.idempotency import (
    IDEMPOTENCY_HEADER,
    REPLAYED_HEADER,
    BeginOutcome,
    Claimed,
    IdempotencyGuard,
    IdempotencyInProgressError,
    IdempotencyKeyReusedError,
    IdempotencyScope,
    IdempotencyService,
    IdempotentReplay,
    Replay,
    StoredResponse,
    canonical_body,
    handle_idempotent_replay,
    idempotent,
    request_fingerprint,
)
from motionile.core.ids import new_id


@dataclass
class Entry:
    record_id: UUID
    request_hash: bytes
    response: StoredResponse | None = None


@dataclass
class InMemoryIdempotencyService(IdempotencyService):
    entries: dict[IdempotencyScope, Entry] = field(default_factory=dict[IdempotencyScope, Entry])
    released: list[UUID] = field(default_factory=list[UUID])

    async def begin(self, target: IdempotencyScope, request_hash: bytes) -> BeginOutcome:
        entry = self.entries.get(target)
        if entry is None:
            entry = Entry(new_id(), request_hash)
            self.entries[target] = entry
            return Claimed(entry.record_id)
        if entry.request_hash != request_hash:
            raise IdempotencyKeyReusedError
        if entry.response is None:
            raise IdempotencyInProgressError(headers={"Retry-After": "1"})
        return Replay(entry.response)

    async def complete(self, record_id: UUID, response: StoredResponse) -> None:
        for entry in self.entries.values():
            if entry.record_id == record_id:
                entry.response = response

    async def release(self, record_id: UUID) -> None:
        self.released.append(record_id)
        self.entries = {key: entry for key, entry in self.entries.items() if entry.record_id != record_id}


@dataclass
class IdempotencyState:
    idempotency: IdempotencyService


class ItemRequest(BaseModel):
    name: str


class ItemResponse(BaseModel):
    id: UUID
    name: str


def make_service() -> InMemoryIdempotencyService:
    settings = make_settings()
    return InMemoryIdempotencyService(
        database=Database(create_engine(settings.database, application_name="tests")),
        clock=FrozenClock(FIXED_NOW),
        ttl=timedelta(hours=24),
        lock_duration=timedelta(seconds=30),
    )


def build_app(service: IdempotencyService) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.add_exception_handler(IdempotentReplay, handle_idempotent_replay)
    app.state.resources = IdempotencyState(service)

    @app.post("/items", status_code=201)
    async def create_item(
        body: ItemRequest, guard: Annotated[IdempotencyGuard, Depends(idempotent("items.create"))]
    ) -> object:
        if body.name == "explode":
            message = "handler failed"
            raise RuntimeError(message)
        if body.name == "skip":
            return {"skipped": True}
        item_id = new_id()
        return await guard.respond(
            ItemResponse(id=item_id, name=body.name),
            status_code=201,
            headers={"Location": f"/items/{item_id}", "X-Debug": "not-replayed"},
        )

    return app


async def post(app: FastAPI, body: object, key: str | None) -> httpx.Response:
    headers = {IDEMPOTENCY_HEADER: key} if key is not None else {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        return await http.post("/items", json=body, headers=headers)


def test_canonical_body_ignores_key_order_and_whitespace() -> None:
    assert canonical_body(b'{"b": 1, "a": [1, 2]}') == canonical_body(b'{"a":[1,2],"b":1}')
    assert canonical_body(b"") == b""
    assert canonical_body(b"not json") == b"not json"


def test_fingerprint_depends_on_method_path_and_body() -> None:
    base = request_fingerprint("POST", "/v1/items", b'{"a":1}')

    assert len(base) == 32
    assert base == request_fingerprint("post", "/v1/items", b'{ "a": 1 }')
    assert base != request_fingerprint("PUT", "/v1/items", b'{"a":1}')
    assert base != request_fingerprint("POST", "/v1/other", b'{"a":1}')
    assert base != request_fingerprint("POST", "/v1/items", b'{"a":2}')


async def test_requires_the_header() -> None:
    response = await post(build_app(make_service()), {"name": "a"}, None)

    assert response.status_code == 400
    assert response.json()["code"] == "idempotency_key_required"


@pytest.mark.parametrize("key", ["", "has space", "x" * 256, "tab\tkey"])
async def test_rejects_malformed_keys(key: str) -> None:
    response = await post(build_app(make_service()), {"name": "a"}, key)

    assert response.status_code == 400


async def test_replays_the_first_response_for_the_same_request() -> None:
    app = build_app(make_service())

    first = await post(app, {"name": "a"}, "key-1")
    second = await post(app, {"name": "a"}, "key-1")

    assert first.status_code == 201
    assert REPLAYED_HEADER not in first.headers
    assert second.status_code == 201
    assert second.json() == first.json()
    assert second.headers[REPLAYED_HEADER] == "true"
    assert second.headers["location"] == first.headers["location"]
    assert "x-debug" not in second.headers


async def test_rejects_key_reuse_with_a_different_body() -> None:
    app = build_app(make_service())

    await post(app, {"name": "a"}, "key-2")
    response = await post(app, {"name": "b"}, "key-2")

    assert response.status_code == 409
    assert response.json()["code"] == "idempotency_key_reused"


async def test_reports_in_progress_with_retry_after() -> None:
    service = make_service()
    target = IdempotencyScope(scope="items.create", user_id=None, key="key-3")
    service.entries[target] = Entry(new_id(), request_fingerprint("POST", "/items", b'{"name":"a"}'))

    response = await post(build_app(service), {"name": "a"}, "key-3")

    assert response.status_code == 409
    assert response.json()["code"] == "idempotency_request_in_progress"
    assert response.headers["retry-after"] == "1"


async def test_releases_the_claim_when_the_handler_fails() -> None:
    service = make_service()
    app = build_app(service)

    with pytest.raises(RuntimeError):
        await post(app, {"name": "explode"}, "key-4")

    assert len(service.released) == 1
    assert service.entries == {}


async def test_releases_the_claim_when_the_handler_never_completes() -> None:
    service = make_service()

    response = await post(build_app(service), {"name": "skip"}, "key-5")

    assert response.status_code == 201
    assert len(service.released) == 1
