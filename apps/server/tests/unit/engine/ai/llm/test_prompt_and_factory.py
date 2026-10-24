import pytest
from pydantic import SecretStr
from tests.fakes.llm import InMemoryUsageLedger
from tests.unit.engine.ai.llm.support import FIXTURES_ROOT, make_call

from motionile.engine.ai.llm.capabilities import provider_of, uses_explicit_cache_control, uses_native_schema
from motionile.engine.ai.llm.config import LlmClientConfig, ProviderKeys, RetryPolicy, StaticBudget, StaticRouting
from motionile.engine.ai.llm.factory import FakeLlmConfig, build_llm_client
from motionile.engine.ai.llm.fake import FakeLlm
from motionile.engine.ai.llm.litellm_client import LiteLlmClient
from motionile.engine.ai.llm.prompt import (
    build_messages,
    cache_breakpoint_indexes,
    json_candidate,
    system_message,
)
from motionile.engine.ai.llm.routing import DEFAULT_ROUTING


@pytest.mark.parametrize(
    ("model", "provider"),
    [
        ("anthropic/claude-sonnet-5-5", "anthropic"),
        ("openai/gpt-4o-mini", "openai"),
        ("claude-haiku-5-5", "anthropic"),
        ("gpt-4o", "openai"),
        ("mystery-model", "unknown"),
    ],
)
def test_the_provider_is_read_from_the_model_name(model: str, provider: str) -> None:
    assert provider_of(model) == provider


@pytest.mark.parametrize(
    ("model", "cached"),
    [
        ("anthropic/claude-sonnet-5-5", True),
        ("bedrock/anthropic.claude-sonnet-5", True),
        ("openai/gpt-4o-mini", False),
        ("gpt-4o", False),
    ],
)
def test_only_claude_models_get_explicit_cache_control(model: str, cached: bool) -> None:
    assert uses_explicit_cache_control(model, {"anthropic"}) is cached


def test_native_schema_needs_provider_and_litellm_support() -> None:
    assert uses_native_schema("openai/gpt-4o-mini", {"openai"}, litellm_supports=True)
    assert not uses_native_schema("openai/gpt-4o-mini", {"openai"}, litellm_supports=False)
    assert not uses_native_schema("anthropic/claude-sonnet-5-5", {"openai"}, litellm_supports=True)


def test_cache_breakpoints_cover_the_first_and_last_block() -> None:
    assert cache_breakpoint_indexes(0) == frozenset()
    assert cache_breakpoint_indexes(1) == frozenset({0})
    assert cache_breakpoint_indexes(4) == frozenset({0, 3})


def test_a_single_cached_system_block_is_marked() -> None:
    message = system_message(["only"], cache_control=True)

    assert message["content"] == [{"type": "text", "text": "only", "cache_control": {"type": "ephemeral"}}]


def test_no_system_message_is_sent_without_system_blocks() -> None:
    messages = build_messages(make_call(system=()), cache_control=True, instruction=None)

    assert [message["role"] for message in messages] == ["user"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a": 1}', '{"a": 1}'),
        ('```json\n{"a": 1}\n```', '{"a": 1}'),
        ('Sure! Here it is: {"a": 1} Hope that helps.', '{"a": 1}'),
        ("no json here", "no json here"),
    ],
)
def test_json_is_extracted_from_chatty_replies(text: str, expected: str) -> None:
    assert json_candidate(text) == expected


def test_retry_delays_double_up_to_the_cap_and_carry_jitter() -> None:
    policy = RetryPolicy(base_delay_seconds=1.0, max_delay_seconds=4.0)

    assert [policy.delay(attempt, 1.0) for attempt in (1, 2, 3, 4)] == [1.0, 2.0, 4.0, 4.0]
    assert policy.delay(3, 0.0) == 2.0


def test_provider_keys_are_not_printed() -> None:
    keys = ProviderKeys(anthropic=SecretStr("sk-ant-secret-value-1234"))

    assert "secret-value" not in repr(keys)
    assert keys.for_provider("openai") is None
    assert keys.for_provider("ollama") is None


def build(use_fake: bool, fake: FakeLlmConfig | None = None) -> object:
    return build_llm_client(
        use_fake=use_fake,
        routing=StaticRouting(DEFAULT_ROUTING),
        ledger=InMemoryUsageLedger(),
        budget=StaticBudget(1_000),
        config=LlmClientConfig(),
        fake=fake,
    )


def test_the_factory_builds_the_fake_in_fake_mode() -> None:
    assert isinstance(build(True, FakeLlmConfig(fixtures_root=FIXTURES_ROOT)), FakeLlm)


def test_the_factory_builds_the_litellm_client_otherwise() -> None:
    assert isinstance(build(False), LiteLlmClient)


def test_the_fake_needs_a_fixtures_root() -> None:
    with pytest.raises(ValueError, match="fixtures root"):
        build(True)
