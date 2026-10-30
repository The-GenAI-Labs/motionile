import asyncio
from collections.abc import Sequence
from uuid import uuid4

import pytest
from tests.fakes.llm import InMemoryUsageLedger
from tests.unit.engine.ai.llm.support import (
    ANTHROPIC_FALLBACK,
    ANTHROPIC_MODEL,
    OPENAI_MODEL,
    Answer,
    RecordingTracer,
    ScriptedCompletions,
    Sleeps,
    client_config,
    completion,
    context,
    half_jitter,
    make_call,
    routing_for,
    valid_answer,
)

from motionile.engine.ai.llm.config import LlmClientConfig, StaticBudget, StaticRouting
from motionile.engine.ai.llm.litellm_client import LiteLlmClient
from motionile.engine.ai.llm.litellm_gateway import litellm
from motionile.engine.ai.llm.models import (
    BudgetExceededError,
    ImageBlock,
    LlmTask,
    LlmTimeoutError,
    LlmUnavailableError,
    LlmUsage,
    ModelOutputInvalidError,
)
from motionile.engine.ai.llm.usage import usage_context

type Steps = Sequence[litellm.ModelResponse | BaseException]


def rate_limited() -> BaseException:
    return litellm.exceptions.RateLimitError("slow down", llm_provider="anthropic", model=ANTHROPIC_MODEL)


def server_error() -> BaseException:
    return litellm.exceptions.InternalServerError("boom", llm_provider="anthropic", model=ANTHROPIC_MODEL)


def timed_out() -> BaseException:
    return litellm.exceptions.Timeout("slow", model=ANTHROPIC_MODEL, llm_provider="anthropic")


def unauthorized() -> BaseException:
    return litellm.exceptions.AuthenticationError("denied", llm_provider="anthropic", model=ANTHROPIC_MODEL)


class Harness:
    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        steps: Steps,
        *,
        models: tuple[str, ...] = (ANTHROPIC_MODEL, ANTHROPIC_FALLBACK),
        budget: int = 1_000_000,
        config: LlmClientConfig | None = None,
    ) -> None:
        self.script = ScriptedCompletions(steps)
        monkeypatch.setattr(litellm, "acompletion", self.script)
        self.ledger = InMemoryUsageLedger()
        self.sleeps = Sleeps()
        self.tracer = RecordingTracer()
        self.client = LiteLlmClient(
            routing=StaticRouting(routing_for(*models)),
            ledger=self.ledger,
            budget=StaticBudget(budget),
            config=config or client_config(),
            tracer=self.tracer,
            sleep=self.sleeps,
            jitter=half_jitter,
        )


async def test_a_valid_reply_is_parsed_and_its_usage_recorded_once(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch, [completion(valid_answer(), prompt_tokens=120, completion_tokens=30, cached=80)])

    result = await harness.client.generate(make_call(), Answer)

    assert result.output == Answer(title="DNS", score=5)
    assert (result.attempts, result.fallback_used) == (1, False)
    assert len(harness.ledger.records) == 1
    recorded = harness.ledger.records[0]
    assert recorded.task is LlmTask.PLAN
    assert recorded.usage.model == ANTHROPIC_MODEL
    assert recorded.usage.provider == "anthropic"
    assert (recorded.usage.input_tokens, recorded.usage.output_tokens, recorded.usage.cached_input_tokens) == (
        120,
        30,
        80,
    )
    assert recorded.context.call_key == f"job:plan:0:{ANTHROPIC_MODEL}"


async def test_the_request_carries_the_route_settings_and_the_explicit_key(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch, [completion(valid_answer())])

    await harness.client.generate(make_call(), Answer)

    request = harness.script.requests[0]
    assert request["model"] == ANTHROPIC_MODEL
    assert request["api_key"] == "sk-ant-test-key-0123456789"
    assert request["timeout"] == 30
    assert request["num_retries"] == 0
    assert request["max_retries"] == 0
    assert request["stream"] is False
    assert request["response_format"] is None


async def test_anthropic_system_blocks_get_cache_control_on_the_first_and_last_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = Harness(monkeypatch, [completion(valid_answer())])
    call = make_call(system=("prompt", "skill one", "skill two"))

    await harness.client.generate(call, Answer)

    messages = harness.script.messages(0)
    system = messages[0]["content"]
    assert [part.get("cache_control") for part in system] == [{"type": "ephemeral"}, None, {"type": "ephemeral"}]
    assert [part["text"] for part in system] == ["prompt", "skill one", "skill two"]


async def test_openai_system_blocks_stay_plain_and_use_the_native_json_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch, [completion(valid_answer())], models=(OPENAI_MODEL,))

    await harness.client.generate(make_call(system=("prompt", "skill")), Answer)

    request = harness.script.requests[0]
    messages = harness.script.messages()
    assert messages[0] == {"role": "system", "content": "prompt\n\nskill"}
    response_format = request["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["schema"]["properties"]["score"]["type"] == "integer"
    assert "json_schema" not in str(messages[-1]["content"])


async def test_models_without_native_schema_get_the_schema_in_the_prompt_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch, [completion(valid_answer())])

    await harness.client.generate(make_call(user=("Explain DNS",)), Answer)

    messages = harness.script.messages(0)
    parts = messages[-1]["content"]
    assert parts[0] == {"type": "text", "text": "Explain DNS"}
    assert "<json_schema>" in parts[-1]["text"]
    assert '"score"' in parts[-1]["text"]


async def test_png_blocks_become_base64_image_content_with_their_label(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch, [completion(valid_answer())])
    call = make_call(LlmTask.VISION_REVIEW, user=("Review these frames", ImageBlock(png=b"\x89PNG", label="hook 16:9")))

    await harness.client.generate(call, Answer)

    messages = harness.script.messages(0)
    parts = messages[-1]["content"]
    assert parts[1] == {"type": "text", "text": "hook 16:9"}
    assert parts[2] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw=="}}


async def test_fenced_json_replies_are_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch, [completion(f"```json\n{valid_answer('Fenced', 3)}\n```")])

    result = await harness.client.generate(make_call(), Answer)

    assert result.output.title == "Fenced"


async def test_transient_errors_back_off_exponentially_with_jitter_and_then_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = Harness(monkeypatch, [rate_limited(), server_error(), completion(valid_answer())])

    result = await harness.client.generate(make_call(), Answer)

    assert result.attempts == 3
    assert result.fallback_used is False
    assert harness.sleeps.delays == [0.75, 1.5]
    assert harness.script.models == [ANTHROPIC_MODEL] * 3
    assert len(harness.ledger.records) == 1


async def test_a_model_that_keeps_failing_hands_over_to_the_next_model(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch, [server_error(), server_error(), server_error(), completion(valid_answer())])

    result = await harness.client.generate(make_call(), Answer)

    assert result.fallback_used is True
    assert result.attempts == 4
    assert harness.script.models == [ANTHROPIC_MODEL] * 3 + [ANTHROPIC_FALLBACK]
    assert harness.ledger.records[0].usage.model == ANTHROPIC_FALLBACK
    assert harness.sleeps.delays == [0.75, 1.5]


async def test_connection_errors_are_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = litellm.exceptions.APIConnectionError("reset", llm_provider="anthropic", model=ANTHROPIC_MODEL)
    harness = Harness(monkeypatch, [connection, completion(valid_answer())])

    result = await harness.client.generate(make_call(), Answer)

    assert result.attempts == 2


async def test_bad_gateway_and_unavailable_are_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    unavailable = litellm.exceptions.ServiceUnavailableError("down", llm_provider="anthropic", model=ANTHROPIC_MODEL)
    gateway = litellm.exceptions.BadGatewayError("bad", llm_provider="anthropic", model=ANTHROPIC_MODEL)
    harness = Harness(monkeypatch, [unavailable, gateway, completion(valid_answer())])

    result = await harness.client.generate(make_call(), Answer)

    assert result.attempts == 3


async def test_every_model_failing_raises_llm_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch, [server_error()] * 6)

    with pytest.raises(LlmUnavailableError):
        await harness.client.generate(make_call(), Answer)

    assert len(harness.script.requests) == 6
    assert harness.ledger.records == []
    assert harness.tracer.spans[0][2].failures == ["llm_unavailable"]
    assert harness.tracer.spans[0][2].ended == 1


async def test_only_timeouts_everywhere_raise_llm_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch, [timed_out()] * 3 + [TimeoutError()] * 3)

    with pytest.raises(LlmTimeoutError):
        await harness.client.generate(make_call(), Answer)


async def test_a_mix_of_timeouts_and_server_errors_raises_llm_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch, [timed_out()] * 3 + [server_error()] * 3)

    with pytest.raises(LlmUnavailableError):
        await harness.client.generate(make_call(), Answer)


async def test_permanent_errors_skip_retries_and_move_to_the_next_model(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch, [unauthorized(), completion(valid_answer())])

    result = await harness.client.generate(make_call(), Answer)

    assert result.fallback_used is True
    assert harness.sleeps.delays == []
    assert result.attempts == 2


async def test_an_unmapped_exception_is_a_bug_and_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch, [RuntimeError("bug")])

    with pytest.raises(RuntimeError):
        await harness.client.generate(make_call(), Answer)

    assert harness.tracer.spans[0][2].failures == ["unexpected_error"]


async def test_a_missing_provider_key_fails_the_model_without_calling_the_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = Harness(monkeypatch, [completion(valid_answer())], models=("ollama/llama3",))

    with pytest.raises(LlmUnavailableError):
        await harness.client.generate(make_call(), Answer)

    assert harness.script.requests == []


async def test_a_schema_violation_is_re_asked_once_with_the_validation_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = '{"title": "DNS", "score": "high"}'
    harness = Harness(
        monkeypatch,
        [completion(broken, prompt_tokens=100, completion_tokens=10), completion(valid_answer(), 140, 12)],
    )

    result = await harness.client.generate(make_call(), Answer)

    assert result.output.score == 5
    assert result.attempts == 2
    assert result.usage.input_tokens == 240
    assert result.usage.output_tokens == 22
    messages = harness.script.messages(1)
    assert messages[-2] == {"role": "assistant", "content": broken}
    assert messages[-1]["role"] == "user"
    assert "score" in messages[-1]["content"]
    assert "integer" in messages[-1]["content"].lower() or "valid" in messages[-1]["content"].lower()
    assert "high" not in messages[-1]["content"]
    assert harness.ledger.keys == [f"job:plan:0:{ANTHROPIC_MODEL}", f"job:plan:1:{ANTHROPIC_MODEL}"]


async def test_a_second_schema_violation_raises_model_output_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch, [completion("not json"), completion('{"title": 3}')])

    with pytest.raises(ModelOutputInvalidError):
        await harness.client.generate(make_call(), Answer)

    assert len(harness.script.requests) == 2
    assert len(harness.ledger.records) == 2
    assert harness.tracer.spans[0][2].failures == ["model_output_invalid"]
    assert len(harness.tracer.spans[0][2].usages) == 1


async def test_the_re_ask_stays_on_the_model_that_answered(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(
        monkeypatch,
        [server_error(), server_error(), server_error(), completion("{}"), completion(valid_answer())],
    )

    result = await harness.client.generate(make_call(), Answer)

    assert result.fallback_used is True
    assert harness.script.models[-2:] == [ANTHROPIC_FALLBACK, ANTHROPIC_FALLBACK]


async def test_a_call_that_would_pass_the_job_budget_is_refused_before_any_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()
    harness = Harness(monkeypatch, [completion(valid_answer())], budget=10_000)
    await harness.ledger.record(
        context(job_id, "earlier"),
        LlmTask.PLAN,
        LlmUsage("anthropic", ANTHROPIC_MODEL, 6_000, 1_000, 0, 0),
    )

    with pytest.raises(BudgetExceededError):
        await harness.client.generate(make_call(call_context=context(job_id)), Answer)

    assert harness.script.requests == []
    assert harness.tracer.spans[0][2].failures == ["budget_exceeded"]


async def test_a_call_inside_the_job_budget_goes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = uuid4()
    harness = Harness(monkeypatch, [completion(valid_answer())], budget=20_000)
    await harness.ledger.record(
        context(job_id, "earlier"),
        LlmTask.PLAN,
        LlmUsage("anthropic", ANTHROPIC_MODEL, 6_000, 1_000, 0, 0),
    )

    result = await harness.client.generate(make_call(call_context=context(job_id)), Answer)

    assert result.output.title == "DNS"


async def test_the_budget_is_not_checked_for_calls_without_a_job(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch, [completion(valid_answer())], budget=1)

    result = await harness.client.generate(make_call(call_context=context(None)), Answer)

    assert result.attempts == 1


async def test_a_model_known_to_the_cost_map_records_a_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(
        monkeypatch, [completion(valid_answer(), prompt_tokens=1_000_000, completion_tokens=0)], models=(OPENAI_MODEL,)
    )

    result = await harness.client.generate(make_call(), Answer)

    assert result.usage.cost_micros_usd > 0


async def test_a_model_unknown_to_the_cost_map_records_zero_cost_and_never_crashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = Harness(monkeypatch, [completion(valid_answer())], models=("openai/gpt-unmapped-9",))

    result = await harness.client.generate(make_call(), Answer)

    assert result.usage.cost_micros_usd == 0
    assert result.usage.model == "openai/gpt-unmapped-9"


async def test_missing_usage_in_the_reply_falls_back_to_estimates(monkeypatch: pytest.MonkeyPatch) -> None:
    bare = litellm.ModelResponse(
        choices=[litellm.Choices(message=litellm.Message(content=valid_answer()), finish_reason="stop")]
    )
    harness = Harness(monkeypatch, [bare])

    result = await harness.client.generate(make_call(), Answer)

    assert result.usage.input_tokens > 0
    assert result.usage.output_tokens > 0


async def test_spans_are_named_after_task_and_stage_and_never_carry_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch, [completion(valid_answer())])
    query = "Explain DNS. Mail me at someone@example.com with header Authorization: Bearer abcdefgh12345678"

    await harness.client.generate(make_call(user=(query,)), Answer)

    name, summary, span = harness.tracer.spans[0]
    assert name == "plan.plan"
    assert "someone@example.com" not in summary
    assert "abcdefgh12345678" not in summary
    assert "Explain DNS" in summary
    assert span.ended == 1
    assert len(span.usages) == 1
    assert span.outputs


async def test_image_bytes_never_reach_the_tracer(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch, [completion(valid_answer())])

    await harness.client.generate(make_call(user=(ImageBlock(png=b"secret-bytes", label="frame"),)), Answer)

    assert harness.tracer.spans[0][1] == "[image: frame]"


async def test_a_hung_provider_is_cut_off_by_the_safety_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    async def hang(**_: object) -> litellm.ModelResponse:
        await asyncio.sleep(30)
        return completion(valid_answer())

    monkeypatch.setattr(litellm, "acompletion", hang)
    tight = LlmClientConfig(keys=client_config().keys, retry=client_config().retry, timeout_grace_seconds=-29.99)
    client = LiteLlmClient(
        routing=StaticRouting(routing_for(ANTHROPIC_MODEL)),
        ledger=InMemoryUsageLedger(),
        budget=StaticBudget(1_000_000),
        config=tight,
        sleep=Sleeps(),
        jitter=half_jitter,
    )

    with pytest.raises(LlmTimeoutError):
        await client.generate(make_call(), Answer)


def test_usage_keys_are_derived_from_the_call_key_round_and_model() -> None:
    base = context(uuid4(), "job:scene:hook")

    first = usage_context(base, "m1", 0)
    again = usage_context(base, "m1", 0)
    reask = usage_context(base, "m1", 1)
    other_model = usage_context(base, "m2", 0)

    assert first.call_key == again.call_key == "job:scene:hook:0:m1"
    assert len({first.call_key, reask.call_key, other_model.call_key}) == 3
    assert first.job_id == base.job_id


async def test_recording_the_same_call_twice_is_idempotent_in_the_ledger() -> None:
    ledger = InMemoryUsageLedger()
    usage = LlmUsage("anthropic", ANTHROPIC_MODEL, 10, 5, 0, 0)

    await ledger.record(usage_context(context(), ANTHROPIC_MODEL, 0), LlmTask.PLAN, usage)
    await ledger.record(usage_context(context(), ANTHROPIC_MODEL, 0), LlmTask.PLAN, usage)

    assert len(ledger.records) == 1
