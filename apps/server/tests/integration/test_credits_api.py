from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.credit_support import new_clock, purge_credit_data
from tests.integration.test_auth import signup

from motionile.core.clock import FrozenClock
from motionile.core.db import after_commit
from motionile.core.ids import new_id
from motionile.core.resources import Resources
from motionile.entrypoints.api import create_app
from motionile.modules.auth import AuthRuntime
from motionile.modules.auth import service as auth_module
from motionile.modules.credits import (
    CreditRef,
    CreditsService,
    GrantCommand,
    ReserveCommand,
    UsageEntry,
    record_usage,
)
from motionile.modules.notifications import FakeDelivery, Notification

PRIMARY_EMAIL = "credits-primary@example.com"
OTHER_EMAIL = "credits-other@example.com"


@dataclass
class Api:
    app: FastAPI
    resources: Resources
    service: CreditsService
    primary: AsyncClient
    other: AsyncClient
    anonymous: AsyncClient
    primary_id: UUID
    other_id: UUID
    clock: FrozenClock

    async def grant(self, user: UUID, amount: int, key: str, *, expires_in: timedelta | None = None) -> None:
        command = GrantCommand(
            user_id=user,
            amount=amount,
            source="purchase",
            key=key,
            expires_at=self.resources.clock.now() + expires_in if expires_in is not None else None,
            ref=CreditRef("payment", new_id()),
        )
        async with self.resources.database.transaction() as session:
            await self.service.grant(session, command)

    async def reserve(self, user: UUID, amount: int, key: str) -> None:
        command = ReserveCommand(user_id=user, amount=amount, ref_type="job", ref_id=new_id(), key=key)
        async with self.resources.database.transaction() as session:
            await self.service.reserve(session, command)

    async def usage(self, user: UUID, key: str, spent: int, *, stage: str = "tts") -> None:
        async with self.resources.database.transaction() as session:
            await record_usage(
                session,
                UsageEntry(
                    user_id=user,
                    stage=stage,
                    provider="elevenlabs",
                    key=key,
                    model="eleven_v3",
                    cost_micros_usd=1_234,
                    credits=spent,
                ),
            )


def client_for(app: FastAPI) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://localhost:8000",
        headers={"Origin": "http://localhost:3000", "X-Turnstile-Token": "test-pass"},
    )


@pytest.fixture
async def api(resources: Resources, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Api]:
    resources.rate_limiter.enabled = False
    clock = new_clock()
    resources.clock = clock
    inbox = FakeDelivery(resources.redis_store)

    def enqueue(fake_resources: Resources, session: AsyncSession, message: Notification) -> None:
        del fake_resources

        async def deliver() -> None:
            await inbox.record(message)

        after_commit(session, deliver)

    monkeypatch.setattr(auth_module, "enqueue_notification", enqueue)
    app = create_app(resources.settings, resources=resources)
    app.state.auth_runtime = AuthRuntime(resources)
    async with client_for(app) as primary, client_for(app) as other, client_for(app) as anonymous:
        primary_id = UUID(await signup(primary, PRIMARY_EMAIL))
        other_id = UUID(await signup(other, OTHER_EMAIL))
        yield Api(
            app=app,
            resources=resources,
            service=CreditsService(resources.clock, resources.settings.billing),
            primary=primary,
            other=other,
            anonymous=anonymous,
            primary_id=primary_id,
            other_id=other_id,
            clock=clock,
        )
    users = [primary_id, other_id]
    await purge_credit_data(resources.database, [])
    async with resources.database.transaction() as session:
        await session.execute(text("SET LOCAL motionile.allow_purge = 'on'"))
        await session.execute(
            text("DELETE FROM audit_log WHERE actor_user_id = ANY(:ids) OR action LIKE 'auth.%'"), {"ids": users}
        )
        await session.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": users})


ENDPOINTS = ["/v1/credits/wallet", "/v1/credits/ledger", "/v1/credits/usage"]


@pytest.mark.parametrize("path", ENDPOINTS)
async def test_every_endpoint_requires_authentication(api: Api, path: str) -> None:
    response = await api.anonymous.get(path)

    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"


async def test_a_user_without_a_wallet_sees_zeros(api: Api) -> None:
    response = await api.primary.get("/v1/credits/wallet")

    assert response.status_code == 200
    assert response.json() == {"balance": 0, "reserved": 0, "available": 0, "expiringSoon": []}


async def test_the_wallet_shows_only_the_callers_credits(api: Api) -> None:
    await api.grant(api.primary_id, 100, "api:primary", expires_in=timedelta(days=3))
    await api.grant(api.primary_id, 40, "api:primary-forever")
    await api.reserve(api.primary_id, 30, "api:primary-hold")
    await api.grant(api.other_id, 500, "api:other", expires_in=timedelta(days=2))

    mine = (await api.primary.get("/v1/credits/wallet")).json()
    theirs = (await api.other.get("/v1/credits/wallet")).json()

    assert (mine["balance"], mine["reserved"], mine["available"]) == (140, 30, 110)
    assert [(lot["source"], lot["remaining"]) for lot in mine["expiringSoon"]] == [("purchase", 100)]
    assert set(mine["expiringSoon"][0]) == {"source", "remaining", "expiresAt"}
    assert (theirs["balance"], theirs["reserved"], theirs["available"]) == (500, 0, 500)
    assert theirs["expiringSoon"][0]["remaining"] == 500


async def test_the_ledger_is_newest_first_paginated_and_owner_scoped(api: Api) -> None:
    for index in range(5):
        api.clock.advance(timedelta(seconds=1))
        await api.grant(api.primary_id, index + 1, f"ledger:primary:{index}")
    await api.grant(api.other_id, 999, "ledger:other")

    first = (await api.primary.get("/v1/credits/ledger", params={"limit": 2})).json()
    assert [item["delta"] for item in first["items"]] == [5, 4]
    assert first["nextCursor"]
    second = (await api.primary.get("/v1/credits/ledger", params={"limit": 2, "cursor": first["nextCursor"]})).json()
    last = (await api.primary.get("/v1/credits/ledger", params={"limit": 2, "cursor": second["nextCursor"]})).json()

    assert [item["delta"] for item in second["items"]] == [3, 2]
    assert [item["delta"] for item in last["items"]] == [1]
    assert last["nextCursor"] is None
    item = first["items"][0]
    assert set(item) == {
        "id",
        "reason",
        "delta",
        "reservedDelta",
        "balanceAfter",
        "reservedAfter",
        "refType",
        "refId",
        "createdAt",
    }
    assert (item["reason"], item["refType"], item["balanceAfter"], item["reservedAfter"]) == (
        "purchase",
        "payment",
        15,
        0,
    )
    assert 999 not in [entry["delta"] for entry in first["items"] + second["items"] + last["items"]]
    others = (await api.other.get("/v1/credits/ledger")).json()
    assert [entry["delta"] for entry in others["items"]] == [999]


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"limit": "x"}, {"unknown": "1"}],
)
async def test_ledger_query_bounds_are_validated(api: Api, params: dict[str, str | int]) -> None:
    response = await api.primary.get("/v1/credits/ledger", params=params)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"


async def test_a_tampered_or_foreign_cursor_is_rejected(api: Api) -> None:
    await api.grant(api.primary_id, 1, "cursor:1")
    await api.grant(api.primary_id, 2, "cursor:2")
    page = (await api.primary.get("/v1/credits/ledger", params={"limit": 1})).json()

    original: str = page["nextCursor"]
    swapped = "B" if original[0] == "A" else "A"
    forged = await api.primary.get("/v1/credits/ledger", params={"cursor": swapped + original[1:]})
    garbage = await api.primary.get("/v1/credits/ledger", params={"cursor": "nonsense"})

    assert (forged.status_code, forged.json()["code"]) == (422, "invalid_cursor")
    assert (garbage.status_code, garbage.json()["code"]) == (422, "invalid_cursor")


async def test_usage_is_newest_first_owner_scoped_and_hides_provider_details(api: Api) -> None:
    for index in range(3):
        api.clock.advance(timedelta(seconds=1))
        await api.usage(api.primary_id, f"usage:primary:{index}", index + 1)
    await api.usage(api.other_id, "usage:other", 77)

    page = (await api.primary.get("/v1/credits/usage", params={"limit": 2})).json()
    rest = (await api.primary.get("/v1/credits/usage", params={"limit": 2, "cursor": page["nextCursor"]})).json()

    spent = [item["credits"] for item in page["items"] + rest["items"]]
    assert sorted(spent) == [1, 2, 3]
    assert rest["nextCursor"] is None
    assert set(page["items"][0]) == {"id", "stage", "credits", "jobId", "publicationId", "createdAt"}
    assert "eleven_v3" not in str(page)
    others = (await api.other.get("/v1/credits/usage")).json()
    assert [item["credits"] for item in others["items"]] == [77]


async def test_usage_can_be_aggregated_per_utc_day(api: Api) -> None:
    await api.usage(api.primary_id, "daily:1", 4)
    await api.usage(api.primary_id, "daily:2", 6, stage="render")
    await api.usage(api.other_id, "daily:3", 50)
    today = api.resources.clock.now().date()

    response = await api.primary.get(
        "/v1/credits/usage",
        params={"aggregate": "daily", "from": (today - timedelta(days=2)).isoformat(), "to": today.isoformat()},
    )

    assert response.status_code == 200
    assert response.json() == {"items": [{"date": today.isoformat(), "credits": 10, "records": 2}]}
    default = (await api.primary.get("/v1/credits/usage", params={"aggregate": "daily"})).json()
    assert default == {"items": [{"date": today.isoformat(), "credits": 10, "records": 2}]}


async def test_usage_range_is_validated(api: Api) -> None:
    today = api.resources.clock.now().date()
    too_wide = await api.primary.get(
        "/v1/credits/usage",
        params={"aggregate": "daily", "from": (today - timedelta(days=366)).isoformat(), "to": today.isoformat()},
    )
    inverted = await api.primary.get(
        "/v1/credits/usage",
        params={"aggregate": "daily", "from": today.isoformat(), "to": (today - timedelta(days=1)).isoformat()},
    )
    widest = await api.primary.get(
        "/v1/credits/usage",
        params={"aggregate": "daily", "from": (today - timedelta(days=365)).isoformat(), "to": today.isoformat()},
    )
    orphan = await api.primary.get("/v1/credits/usage", params={"from": today.isoformat()})
    unknown_mode = await api.primary.get("/v1/credits/usage", params={"aggregate": "weekly"})
    malformed = await api.primary.get("/v1/credits/usage", params={"aggregate": "daily", "from": "yesterday"})

    assert (too_wide.status_code, too_wide.json()["code"]) == (422, "invalid_usage_range")
    assert (inverted.status_code, inverted.json()["code"]) == (422, "invalid_usage_range")
    assert widest.status_code == 200
    assert orphan.status_code == unknown_mode.status_code == malformed.status_code == 422


async def test_the_openapi_contract_names_the_credit_operations(api: Api) -> None:
    schema = api.app.openapi()

    operations = {
        operation["operationId"]
        for path, item in schema["paths"].items()
        if path.startswith("/v1/credits")
        for operation in item.values()
    }
    assert operations == {"credits_wallet", "credits_ledger", "credits_usage"}
    wallet = schema["paths"]["/v1/credits/wallet"]["get"]
    assert {"200", "401", "422", "429"} <= set(wallet["responses"])
