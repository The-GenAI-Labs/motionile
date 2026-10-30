from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.media_support import MediaApi
from tests.integration.test_auth import csrf

from motionile.core.db import Database
from motionile.engine.ai.prompts import PROMPT_KEYS, load_prompt_sources
from motionile.modules.prompts import (
    DatabasePromptStore,
    EvalExecutor,
    EvalOutcome,
    ExternalRun,
    PromptNotActiveError,
    PromptSeeder,
    install_eval_executor,
    record_external_run,
)
from motionile.modules.prompts.dependencies import get_eval_run_service
from motionile.modules.prompts.domain import EvalQueue, RunTrigger
from motionile.modules.prompts.eval_runs import EvalRunService
from motionile.modules.prompts.gate import REQUIRED_SUITES, ActivationGate
from motionile.modules.prompts.repository import SqlPromptRepository
from motionile.modules.prompts.runner import EvalRunner
from motionile.scripts import seed_prompts

ADMIN = "/v1/admin/prompts"
KEY = "planner.storyboard"
DRAFT_BODY = "Internal marker: {{ canary }}.\n\nPlan a concise storyboard in {{ language }}.\n"
DELETE_PROMPT_ROWS = (
    "DELETE FROM eval_runs",
    "UPDATE prompt_templates SET active_version_id = NULL",
    "DELETE FROM prompt_versions",
    "DELETE FROM prompt_templates",
)


@dataclass
class FixedExecutor:
    passed: bool = True
    calls: list[tuple[UUID, str]] = field(default_factory=list[tuple[UUID, str]])

    async def execute(self, run_id: UUID, suite: str, version_ids: Sequence[UUID]) -> EvalOutcome:
        del version_ids
        self.calls.append((run_id, suite))
        return EvalOutcome({"accuracy": 0.95}, self.passed, "2026.10", {"planner": "fake-model"})


@dataclass
class PromptsApi:
    media: MediaApi
    enqueued: list[UUID] = field(default_factory=list[UUID])

    @property
    def database(self) -> Database:
        return self.media.database

    @property
    def manager(self) -> AsyncClient:
        return self.media.other

    @property
    def evaluator(self) -> AsyncClient:
        return self.media.primary

    async def scalar(self, statement: str, **parameters: Any) -> Any:
        async with self.database.transaction() as session:
            return (await session.execute(text(statement), parameters)).scalar()

    async def rows(self, statement: str, **parameters: Any) -> list[Any]:
        async with self.database.transaction() as session:
            return list((await session.execute(text(statement), parameters)).all())

    async def seed(self) -> None:
        await PromptSeeder(self.database.transaction).sync(load_prompt_sources())

    async def version_id(self, key: str, number: int) -> UUID:
        return await self.scalar(
            "SELECT v.id FROM prompt_versions v JOIN prompt_templates t ON t.id = v.template_id "
            "WHERE t.key = :key AND v.version = :number",
            key=key,
            number=number,
        )

    async def pass_suites(self, key: str, number: int, suites: Sequence[str] | None = None) -> None:
        version_id = await self.version_id(key, number)
        async with self.database.transaction() as session:
            for suite in suites if suites is not None else REQUIRED_SUITES[key]:
                await self.record(session, suite, version_id, passed=True)

    @staticmethod
    async def record(session: AsyncSession, suite: str, version_id: UUID, *, passed: bool) -> UUID:
        now = datetime.now(UTC)
        return await record_external_run(
            session,
            ExternalRun(
                suite=suite,
                trigger=RunTrigger.CI,
                dataset_version="2026.10",
                prompt_version_ids=[version_id],
                model_configuration={"planner": "fake-model"},
                scores={"accuracy": 1.0 if passed else 0.1},
                passed=passed,
                started_at=now,
                finished_at=now,
            ),
        )

    async def active_version(self, key: str) -> int | None:
        return await self.scalar(
            "SELECT v.version FROM prompt_templates t JOIN prompt_versions v ON v.id = t.active_version_id "
            "WHERE t.key = :key",
            key=key,
        )

    async def audit_actions(self, key: str) -> list[str]:
        rows = await self.rows(
            "SELECT a.action FROM audit_log a JOIN prompt_templates t ON a.target_id = t.id::text "
            "WHERE t.key = :key ORDER BY a.created_at, a.id",
            key=key,
        )
        return [row[0] for row in rows]


def ignore_enqueue(session: AsyncSession, run_id: UUID, queue: EvalQueue) -> None:
    del session, run_id, queue


def runner_for(api: PromptsApi, executor: EvalExecutor | None) -> EvalRunner:
    resources = api.media.resources
    service = EvalRunService(
        transaction=resources.database.transaction,
        store_factory=SqlPromptRepository,
        gate=ActivationGate(SqlPromptRepository),
        clock=resources.clock,
        enqueue=ignore_enqueue,
    )
    return EvalRunner(service, lambda: executor)


@pytest.fixture
async def prompts_api(media_api: MediaApi) -> AsyncIterator[PromptsApi]:
    api = PromptsApi(media_api)
    resources = media_api.resources

    def enqueue(session: AsyncSession, run_id: UUID, queue: EvalQueue) -> None:
        del session, queue
        api.enqueued.append(run_id)

    def service() -> EvalRunService:
        return EvalRunService(
            transaction=resources.database.transaction,
            store_factory=SqlPromptRepository,
            gate=ActivationGate(SqlPromptRepository),
            clock=resources.clock,
            enqueue=enqueue,
        )

    media_api.app.dependency_overrides[get_eval_run_service] = service
    await media_api.grant_permissions(media_api.other_id, "prompts", "prompts.manage")
    await media_api.grant_permissions(media_api.primary_id, "evals", "evals.run")
    await api.seed()
    yield api
    media_api.app.dependency_overrides.pop(get_eval_run_service, None)
    install_eval_executor(None)
    async with media_api.database.transaction() as session:
        await session.execute(text("SET LOCAL motionile.allow_purge = 'on'"))
        for statement in DELETE_PROMPT_ROWS:
            await session.execute(text(statement))


async def test_the_permission_matrix(prompts_api: PromptsApi) -> None:
    media = prompts_api.media
    version_id = await prompts_api.version_id(KEY, 1)
    reads = [f"{ADMIN}/templates", f"{ADMIN}/templates/{KEY}/versions", f"{ADMIN}/eval-runs"]
    start = {"suite": "planner", "versionIds": [str(version_id)]}

    for path in reads:
        assert (await prompts_api.manager.get(path)).status_code == 200
        assert (await prompts_api.evaluator.get(path)).status_code == 403
        assert (await media.anonymous.get(path)).status_code == 401
    manager_start = await prompts_api.manager.post(f"{ADMIN}/eval-runs", json=start, headers=csrf(prompts_api.manager))
    evaluator_start = await prompts_api.evaluator.post(
        f"{ADMIN}/eval-runs", json=start, headers=csrf(prompts_api.evaluator)
    )
    assert manager_start.status_code == 403
    assert evaluator_start.status_code == 202, evaluator_start.text
    client = prompts_api.evaluator
    blocked = [
        await client.post(f"{ADMIN}/templates/{KEY}/rollback", headers=csrf(client)),
        await client.post(f"{ADMIN}/templates/{KEY}/versions/1/activate", headers=csrf(client)),
        await client.post(f"{ADMIN}/templates/{KEY}/versions", json={"body": DRAFT_BODY}, headers=csrf(client)),
        await client.get(f"{ADMIN}/templates/{KEY}/diff?from=1&to=1"),
    ]
    assert [response.status_code for response in blocked] == [403] * 4


async def test_the_default_admin_role_holds_neither_permission(prompts_api: PromptsApi) -> None:
    granted = await prompts_api.scalar(
        "SELECT count(*) FROM role_permissions rp JOIN roles r ON r.id = rp.role_id "
        "JOIN permissions p ON p.id = rp.permission_id "
        "WHERE r.key = 'admin' AND p.key IN ('prompts.manage', 'evals.run')"
    )

    assert granted == 0


async def test_activation_is_blocked_until_every_required_suite_passed_then_rolls_back(
    prompts_api: PromptsApi,
) -> None:
    manager = prompts_api.manager
    activate = f"{ADMIN}/templates/{KEY}/versions/1/activate"

    blocked = await manager.post(activate, headers=csrf(manager))
    assert (blocked.status_code, blocked.json()["code"]) == (409, "activation_blocked")
    assert blocked.json()["missingSuites"] == ",".join(REQUIRED_SUITES[KEY])

    await prompts_api.pass_suites(KEY, 1, REQUIRED_SUITES[KEY][:-1])
    partial = await manager.post(activate, headers=csrf(manager))
    assert partial.json()["missingSuites"] == REQUIRED_SUITES[KEY][-1]
    assert await prompts_api.active_version(KEY) is None

    await prompts_api.pass_suites(KEY, 1, REQUIRED_SUITES[KEY][-1:])
    activated = await manager.post(activate, headers=csrf(manager))
    assert activated.status_code == 200, activated.text
    assert (activated.json()["version"], activated.json()["isActive"], activated.json()["evalStatus"]) == (
        1,
        True,
        "passed",
    )
    assert await prompts_api.active_version(KEY) == 1

    draft = await manager.post(
        f"{ADMIN}/templates/{KEY}/versions",
        json={"body": DRAFT_BODY, "variables": ["language"]},
        headers=csrf(manager),
    )
    assert draft.status_code == 201, draft.text
    assert (draft.json()["version"], draft.json()["evalStatus"], draft.json()["isActive"]) == (2, "pending", False)
    await prompts_api.pass_suites(KEY, 2)
    second = await manager.post(f"{ADMIN}/templates/{KEY}/versions/2/activate", headers=csrf(manager))
    assert second.status_code == 200
    assert await prompts_api.active_version(KEY) == 2

    rolled = await manager.post(f"{ADMIN}/templates/{KEY}/rollback", headers=csrf(manager))
    assert (rolled.status_code, rolled.json()["version"]) == (200, 1)
    assert await prompts_api.active_version(KEY) == 1
    again = await manager.post(f"{ADMIN}/templates/{KEY}/rollback", headers=csrf(manager))
    assert (again.status_code, again.json()["code"]) == (409, "no_previous_version")

    assert await prompts_api.audit_actions(KEY) == [
        "prompts.draft_created",
        "prompts.version_activated",
        "prompts.draft_created",
        "prompts.version_activated",
        "prompts.version_rolled_back",
    ]


async def test_a_failed_suite_blocks_activation_and_is_reported(prompts_api: PromptsApi) -> None:
    manager = prompts_api.manager
    version_id = await prompts_api.version_id(KEY, 1)
    await prompts_api.pass_suites(KEY, 1, ("planner", "safety"))
    async with prompts_api.database.transaction() as session:
        await PromptsApi.record(session, "cost", version_id, passed=False)

    response = await manager.post(f"{ADMIN}/templates/{KEY}/versions/1/activate", headers=csrf(manager))

    assert (response.status_code, response.json()["failedSuites"], response.json()["missingSuites"]) == (
        409,
        "cost",
        "",
    )
    listing = (await manager.get(f"{ADMIN}/templates/{KEY}/versions")).json()["items"]
    assert listing[0]["evalStatus"] == "failed"


async def test_drafts_are_validated_and_deduplicated(prompts_api: PromptsApi) -> None:
    manager = prompts_api.manager
    path = f"{ADMIN}/templates/{KEY}/versions"

    invalid = await manager.post(path, json={"body": DRAFT_BODY}, headers=csrf(manager))
    ok = await manager.post(path, json={"body": DRAFT_BODY, "variables": ["language"]}, headers=csrf(manager))
    duplicate = await manager.post(path, json={"body": DRAFT_BODY, "variables": ["language"]}, headers=csrf(manager))
    extra = await manager.post(path, json={"body": DRAFT_BODY, "other": 1}, headers=csrf(manager))
    missing = await manager.post(
        f"{ADMIN}/templates/missing.template/versions",
        json={"body": DRAFT_BODY, "variables": ["language"]},
        headers=csrf(manager),
    )

    assert (invalid.status_code, invalid.json()["code"]) == (422, "prompt_draft_invalid")
    assert ok.status_code == 201
    assert (duplicate.status_code, duplicate.json()["code"]) == (409, "prompt_version_exists")
    assert extra.status_code == 422
    assert missing.status_code == 404
    assert await prompts_api.active_version(KEY) is None


async def test_responses_never_carry_prompt_text_or_canaries_except_the_diff(prompts_api: PromptsApi) -> None:
    manager = prompts_api.manager
    canaries = [row[0] for row in await prompts_api.rows("SELECT canary FROM prompt_versions")]
    bodies = [row[0] for row in await prompts_api.rows("SELECT body FROM prompt_versions")]
    await manager.post(
        f"{ADMIN}/templates/{KEY}/versions",
        json={"body": DRAFT_BODY, "variables": ["language"]},
        headers=csrf(manager),
    )

    texts = [
        (await manager.get(f"{ADMIN}/templates")).text,
        (await manager.get(f"{ADMIN}/templates/{KEY}/versions")).text,
        (await manager.get(f"{ADMIN}/eval-runs")).text,
    ]

    for payload in texts:
        assert not any(canary in payload for canary in canaries)
        assert not any(body.strip()[:80] in payload for body in bodies)
        assert "body" not in payload.lower().replace("checksumprefix", "")


async def test_the_diff_redacts_canaries_is_not_cacheable_and_is_audited(prompts_api: PromptsApi) -> None:
    manager = prompts_api.manager
    await manager.post(
        f"{ADMIN}/templates/{KEY}/versions",
        json={"body": DRAFT_BODY, "variables": ["language"]},
        headers=csrf(manager),
    )
    canaries = [row[0] for row in await prompts_api.rows("SELECT canary FROM prompt_versions")]

    response = await manager.get(f"{ADMIN}/templates/{KEY}/diff?from=1&to=2")

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert (payload["fromVersion"], payload["toVersion"]) == (1, 2)
    assert payload["added"] > 0
    assert not any(canary in response.text for canary in canaries)
    assert "{{ canary }}" not in response.text
    await manager.get(f"{ADMIN}/templates/{KEY}/diff?from=2&to=1")
    assert (await prompts_api.audit_actions(KEY)).count("prompts.diff_viewed") == 2
    assert (await manager.get(f"{ADMIN}/templates/{KEY}/diff?from=1&to=9")).status_code == 404
    assert (await manager.get(f"{ADMIN}/templates/{KEY}/diff?from=0&to=1")).status_code == 422


async def test_an_eval_run_goes_from_running_to_finished_and_completes_the_version(prompts_api: PromptsApi) -> None:
    evaluator, manager = prompts_api.evaluator, prompts_api.manager
    version_id = await prompts_api.version_id(KEY, 1)
    executor = FixedExecutor()
    install_eval_executor(lambda _: executor)
    runner = runner_for(prompts_api, executor)

    for suite in REQUIRED_SUITES[KEY]:
        started = await evaluator.post(
            f"{ADMIN}/eval-runs", json={"suite": suite, "versionIds": [str(version_id)]}, headers=csrf(evaluator)
        )
        assert started.status_code == 202, started.text
        body = started.json()
        assert (body["status"], body["trigger"], body["datasetVersion"], body["passed"]) == (
            "running",
            "admin",
            "pending",
            None,
        )
        assert body["createdBy"] == str(prompts_api.media.primary_id)
        await runner.run(UUID(body["id"]))

    assert len(prompts_api.enqueued) == len(REQUIRED_SUITES[KEY])
    run_id = prompts_api.enqueued[0]
    finished = (await manager.get(f"{ADMIN}/eval-runs/{run_id}")).json()
    assert (finished["status"], finished["passed"], finished["datasetVersion"]) == ("finished", True, "2026.10")
    assert finished["scores"] == {"accuracy": 0.95}
    assert finished["modelsUsed"] == {"planner": "fake-model"}
    assert finished["promptVersionIds"] == [str(version_id)]
    assert finished["finishedAt"] is not None
    assert await prompts_api.scalar("SELECT eval_status FROM prompt_versions WHERE id = :id", id=version_id) == "passed"
    activated = await manager.post(f"{ADMIN}/templates/{KEY}/versions/1/activate", headers=csrf(manager))
    assert activated.status_code == 200
    listing = (await manager.get(f"{ADMIN}/eval-runs?suite=planner&status=finished&limit=1")).json()
    assert [item["suite"] for item in listing["items"]] == ["planner"]
    assert (await manager.get(f"{ADMIN}/eval-runs?status=bogus")).status_code == 422
    assert (await manager.get(f"{ADMIN}/eval-runs/{UUID(int=5)}")).status_code == 404
    started_audits = await prompts_api.scalar(
        "SELECT count(*) FROM audit_log WHERE action = 'prompts.eval_started' AND actor_user_id = :id",
        id=prompts_api.media.primary_id,
    )
    assert started_audits == len(REQUIRED_SUITES[KEY])


async def test_without_an_installed_executor_the_run_errors(prompts_api: PromptsApi) -> None:
    evaluator = prompts_api.evaluator
    version_id = await prompts_api.version_id(KEY, 1)
    started = await evaluator.post(
        f"{ADMIN}/eval-runs", json={"suite": "planner", "versionIds": [str(version_id)]}, headers=csrf(evaluator)
    )
    runner = runner_for(prompts_api, None)

    await runner.run(UUID(started.json()["id"]))

    row = (
        await prompts_api.rows(
            "SELECT status, error_code, passed FROM eval_runs WHERE id = :id", id=UUID(started.json()["id"])
        )
    )[0]
    assert tuple(row) == ("errored", "eval_executor_unavailable", None)
    rejected = [
        await evaluator.post(f"{ADMIN}/eval-runs", json={"suite": suite, "versionIds": ids}, headers=csrf(evaluator))
        for suite, ids in (("unknown", [str(version_id)]), ("planner", []), ("planner", [str(UUID(int=7))]))
    ]
    assert [response.status_code for response in rejected] == [422, 422, 404]


async def test_the_seed_command_syncs_and_bootstraps_against_a_real_database(
    prompts_api: PromptsApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with prompts_api.database.transaction() as session:
        await session.execute(text("SET LOCAL motionile.allow_purge = 'on'"))
        for statement in DELETE_PROMPT_ROWS:
            await session.execute(text(statement))
    monkeypatch.setattr(seed_prompts, "get_settings", lambda: prompts_api.media.resources.settings)

    assert await seed_prompts.run(bootstrap=False) == 0
    assert await prompts_api.scalar("SELECT count(*) FROM prompt_templates") == len(PROMPT_KEYS)
    assert await prompts_api.scalar("SELECT count(*) FROM prompt_templates WHERE active_version_id IS NOT NULL") == 0
    assert await seed_prompts.run(bootstrap=False) == 0
    assert await prompts_api.scalar("SELECT count(*) FROM prompt_versions") == len(PROMPT_KEYS)

    assert await seed_prompts.run(bootstrap=True) == 0
    assert await prompts_api.scalar("SELECT count(*) FROM prompt_templates WHERE active_version_id IS NOT NULL") == len(
        PROMPT_KEYS
    )
    store = DatabasePromptStore(prompts_api.database.transaction)
    prompts = await store.all_active()
    assert {prompt.key for prompt in prompts} == set(PROMPT_KEYS)
    active = await store.active(KEY)
    assert (active.version, "canary" in active.variables) == (1, True)
    assert active.canary in (
        await prompts_api.scalar("SELECT canary FROM prompt_versions WHERE id = :id", id=active.version_id)
    )


async def test_a_template_without_an_active_version_raises_the_typed_error(prompts_api: PromptsApi) -> None:
    store = DatabasePromptStore(prompts_api.database.transaction)

    with pytest.raises(PromptNotActiveError):
        await store.active(KEY)
