import math
from dataclasses import dataclass, field

import pytest
from pydantic import SecretStr
from tests.fakes.llm import InMemoryUsageLedger
from tests.unit.engine.ai.llm.support import Sleeps, context, half_jitter

from motionile.engine.ai.llm.config import RetryPolicy
from motionile.engine.ai.llm.embeddings import EmbedderConfig, FakeEmbedder, LiteLlmEmbedder, hashed_vector
from motionile.engine.ai.llm.litellm_gateway import litellm
from motionile.engine.ai.llm.models import LlmTask, LlmUnavailableError

MODEL = "openai/text-embedding-3-small"


def cosine(first: list[float], second: list[float]) -> float:
    return sum(a * b for a, b in zip(first, second, strict=True))


async def test_fake_vectors_are_deterministic_normalized_and_of_the_configured_size() -> None:
    embedder = FakeEmbedder(dimensions=256)

    first = await embedder.embed(["how DNS resolves a name", "binary search"], context())
    second = await embedder.embed(["how DNS resolves a name", "binary search"], context())

    assert first == second
    assert all(len(vector) == 256 for vector in first)
    assert all(math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0) for vector in first)
    assert embedder.dimensions == 256
    assert embedder.model == "fake-embedding"


async def test_texts_that_share_words_are_closer_than_unrelated_texts() -> None:
    embedder = FakeEmbedder(dimensions=1536)

    query, related, unrelated = await embedder.embed(
        [
            "how a dns resolver finds an ip address",
            "dns resolver and ip address lookup",
            "photosynthesis in green leaves",
        ],
        context(),
    )

    assert cosine(query, related) > 0.5
    assert cosine(query, related) > cosine(query, unrelated) + 0.4


async def test_word_order_case_and_punctuation_do_not_matter() -> None:
    assert hashed_vector("Binary, SEARCH!", 128) == hashed_vector("search binary", 128)


async def test_empty_text_gets_a_valid_unit_vector() -> None:
    vector = hashed_vector("   ", 64)

    assert sum(v * v for v in vector) == 1.0


async def test_the_fake_embedder_records_usage_as_the_embed_stage() -> None:
    ledger = InMemoryUsageLedger()

    await FakeEmbedder(dimensions=64, ledger=ledger).embed(["one", "two"], context(call_key="skills"))

    record = ledger.records[0]
    assert record.context.stage == "embed"
    assert record.context.call_key == "skills:embed:0"
    assert record.task is LlmTask.ROUTE
    assert record.usage.cost_micros_usd == 0
    assert record.usage.output_tokens == 0


@dataclass
class ScriptedEmbeddings:
    steps: list[litellm.EmbeddingResponse | BaseException]
    requests: list[dict[str, object]] = field(default_factory=list[dict[str, object]])

    async def __call__(self, **kwargs: object) -> litellm.EmbeddingResponse:
        self.requests.append(kwargs)
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


def embedding_response(count: int, dimensions: int, prompt_tokens: int = 7) -> litellm.EmbeddingResponse:
    return litellm.EmbeddingResponse(
        model="text-embedding-3-small",
        data=[{"object": "embedding", "index": index, "embedding": [0.5] * dimensions} for index in range(count)],
        usage=litellm.Usage(prompt_tokens=prompt_tokens, total_tokens=prompt_tokens),
    )


def embedder(ledger: InMemoryUsageLedger, sleeps: Sleeps | None = None, batch_size: int = 128) -> LiteLlmEmbedder:
    config = EmbedderConfig(
        model=MODEL,
        dimensions=4,
        api_key=SecretStr("sk-test-key-0123456789"),
        batch_size=batch_size,
        retry=RetryPolicy(attempts_per_model=3, base_delay_seconds=1.0, max_delay_seconds=4.0),
    )
    return LiteLlmEmbedder(config, ledger, sleep=sleeps or Sleeps(), jitter=half_jitter)


async def test_embeddings_are_requested_with_the_explicit_key_and_dimensions(monkeypatch: pytest.MonkeyPatch) -> None:
    script = ScriptedEmbeddings([embedding_response(2, 4, prompt_tokens=1_000_000)])
    monkeypatch.setattr(litellm, "aembedding", script)
    ledger = InMemoryUsageLedger()

    vectors = await embedder(ledger).embed(["a", "b"], context(call_key="skill-seed"))

    assert vectors == [[0.5] * 4, [0.5] * 4]
    request = script.requests[0]
    assert request["model"] == MODEL
    assert request["input"] == ["a", "b"]
    assert request["dimensions"] == 4
    assert request["api_key"] == "sk-test-key-0123456789"
    record = ledger.records[0]
    assert (record.context.stage, record.context.call_key) == ("embed", "skill-seed:embed:0")
    assert record.usage.input_tokens == 1_000_000
    assert record.usage.output_tokens == 0
    assert record.usage.model == MODEL
    assert record.usage.cost_micros_usd > 0


async def test_large_inputs_are_split_into_batches_with_their_own_usage_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    script = ScriptedEmbeddings([embedding_response(2, 4), embedding_response(1, 4)])
    monkeypatch.setattr(litellm, "aembedding", script)
    ledger = InMemoryUsageLedger()

    vectors = await embedder(ledger, batch_size=2).embed(["a", "b", "c"], context(call_key="k"))

    assert len(vectors) == 3
    assert [request["input"] for request in script.requests] == [["a", "b"], ["c"]]
    assert ledger.keys == ["k:embed:0", "k:embed:1"]


async def test_transient_failures_are_retried_with_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    limited = litellm.exceptions.RateLimitError("slow", llm_provider="openai", model=MODEL)
    script = ScriptedEmbeddings([limited, embedding_response(1, 4)])
    monkeypatch.setattr(litellm, "aembedding", script)
    sleeps = Sleeps()

    await embedder(InMemoryUsageLedger(), sleeps).embed(["a"], context())

    assert sleeps.delays == [0.75]
    assert len(script.requests) == 2


async def test_persistent_failures_raise_llm_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = litellm.exceptions.InternalServerError("boom", llm_provider="openai", model=MODEL)
    script = ScriptedEmbeddings([broken, broken, broken])
    monkeypatch.setattr(litellm, "aembedding", script)
    ledger = InMemoryUsageLedger()

    with pytest.raises(LlmUnavailableError):
        await embedder(ledger).embed(["a"], context())

    assert ledger.records == []


async def test_a_wrong_number_of_vectors_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(litellm, "aembedding", ScriptedEmbeddings([embedding_response(1, 4)]))

    with pytest.raises(LlmUnavailableError):
        await embedder(InMemoryUsageLedger()).embed(["a", "b"], context())


async def test_a_missing_key_never_reaches_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    script = ScriptedEmbeddings([])
    monkeypatch.setattr(litellm, "aembedding", script)
    keyless = LiteLlmEmbedder(EmbedderConfig(model=MODEL, dimensions=4), InMemoryUsageLedger())

    with pytest.raises(LlmUnavailableError):
        await keyless.embed(["a"], context())

    assert script.requests == []
