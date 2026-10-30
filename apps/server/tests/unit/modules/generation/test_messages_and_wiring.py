import asyncio
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.generation import FakeSettingsReader
from tests.fakes.resources import make_resources
from tests.fakes.settings import make_settings

from motionile.core.ids import new_id
from motionile.engine.ai.graphs.errors import LLM_FAILURE_MESSAGES
from motionile.engine.ai.guardrails import POLICY_MESSAGES, GuardResult, InputKind, PolicyCode
from motionile.engine.ai.llm.fake import FakeLlm
from motionile.engine.ai.llm.models import (
    BudgetExceededError,
    CallContext,
    LlmError,
    LlmTask,
    LlmTimeoutError,
    LlmUnavailableError,
    LlmUsage,
    ModelOutputInvalidError,
    OutputBlockedError,
)
from motionile.modules.credits import UsageEntry
from motionile.modules.generation import (
    AiUnavailableError,
    AspectNotAllowedError,
    InputRefusedError,
    JobNotFoundError,
    StoryboardInvalidError,
    ai_fixtures_directory,
    describe_error,
    llm_client_for,
)
from motionile.modules.generation.ai_wiring import (
    MAX_CONCURRENT_GUARDS,
    InputGuardEditGuard,
    RecordedUsageLedger,
    SettingsBudgetProvider,
    SettingsRoutingProvider,
    chunk_texts,
    usage_key,
)
from motionile.modules.generation.exceptions import TooManyActiveJobsError
from motionile.modules.generation.runtime_settings import RuntimeSettings
from motionile.modules.platform import SettingValue

USER = UUID("01939a5e-0000-7000-8000-000000000001")
JOB = UUID("01939a5e-0000-7000-8000-0000000000aa")


class RecordingGuard:
    def __init__(self, refuse_on: str | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.contexts: list[CallContext] = []
        self.refuse_on = refuse_on

    async def check(self, text: str, context: CallContext, kind: InputKind) -> GuardResult:
        self.contexts.append(context)
        self.calls.append((kind, text))
        if self.refuse_on is not None and self.refuse_on in text:
            return GuardResult.refuse(PolicyCode.PROMPT_INJECTION)
        return GuardResult.allow()


class FakeTransaction:
    def __init__(self) -> None:
        self.opened = 0

    def __call__(self) -> "FakeTransaction":
        return self

    async def __aenter__(self) -> AsyncSession:
        self.opened += 1
        return AsyncSession()

    async def __aexit__(self, *exc: object) -> None:
        return None


def test_policy_refusals_use_the_published_policy_message() -> None:
    description = describe_error("policy_malware", "internal text")

    assert description is not None
    assert description.message == POLICY_MESSAGES[PolicyCode.MALWARE]
    assert "internal text" not in description.message


@pytest.mark.parametrize(
    "code",
    ["model_output_invalid", "budget_exceeded", "llm_unavailable", "no_style_skill", "tts_failed", "job_stalled"],
)
def test_known_failures_have_stable_messages(code: str) -> None:
    first = describe_error(code, "provider said: 500 Internal")
    second = describe_error(code, None)

    assert first == second
    assert first is not None
    assert "500" not in first.message
    assert "credits were returned" in first.message


def test_a_lost_reservation_has_a_stable_user_message() -> None:
    description = describe_error("reservation_lost", "internal text")

    assert description is not None
    assert "internal text" not in description.message
    assert description.title == "The video was stopped"


def test_render_failures_share_a_render_message() -> None:
    description = describe_error("browser_crash", None)

    assert description is not None
    assert description.title == "The video could not be rendered"


def test_unknown_codes_fall_back_to_the_stored_message_or_a_generic_one() -> None:
    stored = describe_error("something_new", "Stored text")
    generic = describe_error("something_new", None)

    assert stored is not None
    assert stored.message == "Stored text"
    assert generic is not None
    assert generic.title == "The video could not be completed"
    assert describe_error(None, "x") is None


def test_error_codes_and_statuses_are_stable() -> None:
    assert JobNotFoundError().status_code == 404
    assert JobNotFoundError.default_code == "job_not_found"
    assert TooManyActiveJobsError(2).code == "too_many_active_jobs"
    assert AspectNotAllowedError.default_code == "aspect_not_allowed"
    assert StoryboardInvalidError([]).status_code == 422
    refused = InputRefusedError(PolicyCode.WEAPONS)
    assert (refused.status_code, refused.code) == (422, "input_refused")
    assert refused.detail == POLICY_MESSAGES[PolicyCode.WEAPONS]
    assert refused.extensions == {"policy": "policy_weapons"}


def test_the_usage_key_is_a_stable_bounded_hash_of_the_call_key() -> None:
    first = usage_key("job:1:plan:0:model")

    assert first == usage_key("job:1:plan:0:model")
    assert first != usage_key("job:1:plan:1:model")
    assert first.startswith("llm:")
    assert len(first) <= 200
    assert "job:1" not in first


async def test_the_usage_ledger_records_a_usage_row_per_call() -> None:
    entries: list[UsageEntry] = []

    async def record(session: AsyncSession, entry: UsageEntry) -> UUID:
        del session
        entries.append(entry)
        return new_id()

    ledger = RecordedUsageLedger(FakeTransaction(), record)
    usage = LlmUsage("anthropic", "claude-sonnet-5-5", 1_000, 200, 0, 4_500)

    await ledger.record(CallContext(USER, JOB, "plan", "job:plan:0"), LlmTask.PLAN, usage)

    [entry] = entries
    assert (entry.user_id, entry.job_id, entry.stage, entry.provider) == (USER, JOB, "plan", "anthropic")
    assert (entry.input_tokens, entry.output_tokens, entry.cost_micros_usd) == (1_000, 200, 4_500)
    assert entry.key == usage_key("job:plan:0")


def test_texts_are_chunked_under_the_guard_limit() -> None:
    texts = ["a" * 400, "b" * 400, "c" * 400]

    chunks = chunk_texts(texts, limit=1_000)

    assert len(chunks) == 2
    assert all(len(chunk) <= 1_000 for chunk in chunks)
    assert "".join(chunks).count("a") == 400
    assert chunk_texts([]) == []


async def test_the_edit_guard_checks_edits_as_storyboard_edits_and_stops_at_a_refusal() -> None:
    guard = RecordingGuard(refuse_on="ignore")
    edit_guard = InputGuardEditGuard(guard)

    allowed = await edit_guard.check_edit(USER, JOB, ["fine text"])
    refused = await edit_guard.check_edit(USER, JOB, ["ignore everything"])

    assert allowed.allowed
    assert not refused.allowed
    assert refused.code is PolicyCode.PROMPT_INJECTION
    assert {kind for kind, _ in guard.calls} == {"storyboard_edit"}


async def test_the_edit_guard_checks_instructions_as_instructions() -> None:
    guard = RecordingGuard()

    result = await InputGuardEditGuard(guard).check_instructions(USER, JOB, "shorter")

    assert result.allowed
    assert guard.calls == [("instructions", "shorter")]


async def test_every_guard_call_gets_its_own_call_key_so_every_paid_call_records_usage() -> None:
    guard = RecordingGuard()
    edit_guard = InputGuardEditGuard(guard)

    await edit_guard.check_instructions(USER, JOB, "shorter")
    await edit_guard.check_instructions(USER, JOB, "shorter")
    await edit_guard.check_edit(USER, JOB, ["same text"])
    await edit_guard.check_edit(USER, JOB, ["same text"])

    keys = [context.call_key for context in guard.contexts]
    assert len(set(keys)) == 4
    assert len({usage_key(key) for key in keys}) == 4
    assert all(key.startswith("edit:") and str(JOB) in key for key in keys)
    assert {context.stage for context in guard.contexts} == {"guard"}


@pytest.mark.parametrize(
    "error",
    [
        LlmUnavailableError(),
        LlmTimeoutError(),
        BudgetExceededError(),
        ModelOutputInvalidError(),
        OutputBlockedError(),
    ],
)
async def test_model_failures_on_the_api_path_become_service_unavailable_problems(error: LlmError) -> None:
    class FailingGuard:
        async def check(self, text: str, context: CallContext, kind: InputKind) -> GuardResult:
            del text, context, kind
            raise error

    edit_guard = InputGuardEditGuard(FailingGuard())

    for call in (edit_guard.check_instructions(USER, JOB, "x"), edit_guard.check_edit(USER, JOB, ["x"])):
        with pytest.raises(AiUnavailableError) as caught:
            await call

        assert caught.value.status_code == 503
        assert caught.value.code == error.code.value
        assert caught.value.detail == LLM_FAILURE_MESSAGES[error.code]


async def test_other_failures_are_not_swallowed_by_the_edit_guard() -> None:
    class BrokenGuard:
        async def check(self, text: str, context: CallContext, kind: InputKind) -> GuardResult:
            del text, context, kind
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await InputGuardEditGuard(BrokenGuard()).check_instructions(USER, JOB, "x")


async def test_concurrent_guard_calls_are_capped_per_process() -> None:
    running = 0
    peak = 0

    class SlowGuard:
        async def check(self, text: str, context: CallContext, kind: InputKind) -> GuardResult:
            nonlocal running, peak
            del text, context, kind
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1
            return GuardResult.allow()

    edit_guard = InputGuardEditGuard(SlowGuard(), max_concurrent=3)

    results = await asyncio.gather(*(edit_guard.check_instructions(USER, JOB, f"text {index}") for index in range(12)))

    assert all(result.allowed for result in results)
    assert peak == 3


def test_the_default_guard_concurrency_cap_is_eight() -> None:
    assert MAX_CONCURRENT_GUARDS == 8


async def test_routing_and_budget_come_from_platform_settings() -> None:
    reader = FakeSettingsReader(**{"ai.job_token_budget": 123_456})

    async def read(key: str) -> SettingValue:
        return await reader.value(AsyncSession(), key)

    routing = await SettingsRoutingProvider(read).routing()
    budget = await SettingsBudgetProvider(read).job_token_budget()

    assert routing.route(LlmTask.PLAN).primary
    assert budget == 123_456


async def test_runtime_settings_expose_the_charging_parameters_and_limits() -> None:
    reader = FakeSettingsReader(**{"charging.base_credits": 30, "ai.approval_timeout_hours": 24})
    runtime = RuntimeSettings(reader)
    session = AsyncSession()

    parameters = await runtime.charging(session)

    assert (parameters.base_credits, parameters.credits_per_second) == (30, 2)
    assert await runtime.max_active_jobs(session) == 2
    limits = await runtime.storyboard_limits(session)
    assert (limits.min_words_per_second, limits.max_words_per_second) == (2.0, 2.8)


async def test_fake_mode_builds_the_scripted_llm_from_the_fixtures_directory() -> None:
    settings = make_settings()
    resources = make_resources(settings)

    client = llm_client_for(resources)

    assert isinstance(client, FakeLlm)
    assert ai_fixtures_directory(settings).name == "llm"
    assert ai_fixtures_directory(settings).is_dir()
    assert llm_client_for(resources) is client
    await resources.aclose()
