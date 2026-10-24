import asyncio
import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

import structlog
from pydantic import SecretStr

from motionile.engine.ai.llm import litellm_gateway as gateway
from motionile.engine.ai.llm.capabilities import provider_of
from motionile.engine.ai.llm.config import ProviderKeys, RetryPolicy
from motionile.engine.ai.llm.litellm_client import Jitter, Sleep, secure_jitter
from motionile.engine.ai.llm.litellm_gateway import FailureKind
from motionile.engine.ai.llm.models import CallContext, LlmTask, LlmUnavailableError, LlmUsage, UsageLedger
from motionile.engine.ai.llm.usage import estimate_tokens

logger = structlog.get_logger(__name__)

EMBED_STAGE = "embed"
WORD_PATTERN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class EmbedderConfig:
    model: str
    dimensions: int
    api_key: SecretStr | None = field(default=None, repr=False)
    timeout_seconds: float = 30.0
    batch_size: int = 128
    retry: RetryPolicy = field(default_factory=RetryPolicy)

    @classmethod
    def with_keys(cls, model: str, dimensions: int, keys: ProviderKeys) -> "EmbedderConfig":
        return cls(model=model, dimensions=dimensions, api_key=keys.for_provider(provider_of(model)))


def embed_context(context: CallContext, batch_index: int) -> CallContext:
    return replace(context, stage=EMBED_STAGE, call_key=f"{context.call_key}:embed:{batch_index}")


class LiteLlmEmbedder:
    def __init__(
        self,
        config: EmbedderConfig,
        ledger: UsageLedger,
        *,
        sleep: Sleep = asyncio.sleep,
        jitter: Jitter = secure_jitter,
    ) -> None:
        self._config = config
        self._ledger = ledger
        self._sleep = sleep
        self._jitter = jitter

    @property
    def model(self) -> str:
        return self._config.model

    @property
    def dimensions(self) -> int:
        return self._config.dimensions

    async def embed(self, texts: Sequence[str], context: CallContext) -> list[list[float]]:
        vectors: list[list[float]] = []
        size = self._config.batch_size
        for batch_index, start in enumerate(range(0, len(texts), size)):
            vectors.extend(await self._embed_batch(texts[start : start + size], context, batch_index))
        return vectors

    async def _embed_batch(self, texts: Sequence[str], context: CallContext, batch_index: int) -> list[list[float]]:
        completion = await self._request(texts)
        input_tokens = completion.input_tokens
        if input_tokens is None:
            input_tokens = sum(estimate_tokens(text) for text in texts)
        usage = LlmUsage(
            provider=provider_of(self._config.model),
            model=self._config.model,
            input_tokens=input_tokens,
            output_tokens=0,
            cached_input_tokens=0,
            cost_micros_usd=completion.cost_micros_usd,
        )
        await self._ledger.record(embed_context(context, batch_index), LlmTask.ROUTE, usage)
        return completion.vectors

    async def _request(self, texts: Sequence[str]) -> gateway.EmbeddingCompletion:
        key = self._config.api_key
        if key is None:
            logger.warning("llm.provider_not_configured", model=self._config.model)
            raise LlmUnavailableError
        policy = self._config.retry
        attempt = 0
        while True:
            attempt += 1
            try:
                return await gateway.embed(
                    model=self._config.model,
                    texts=texts,
                    dimensions=self._config.dimensions,
                    timeout_seconds=self._config.timeout_seconds,
                    api_key=key.get_secret_value(),
                )
            except Exception as error:
                kind = gateway.classify_failure(error)
                if kind is None:
                    raise
                logger.warning(
                    "llm.embedding_failed",
                    model=self._config.model,
                    attempt=attempt,
                    kind=kind.value,
                    error=type(error).__name__,
                )
                if kind is FailureKind.PERMANENT or attempt == policy.attempts_per_model:
                    raise LlmUnavailableError from None
                await self._sleep(policy.delay(attempt, self._jitter()))


def hashed_bucket(word: str, dimensions: int) -> tuple[int, float]:
    digest = hashlib.sha256(word.encode("utf-8")).digest()
    index = int.from_bytes(digest[:8], "big") % dimensions
    sign = 1.0 if digest[8] % 2 == 0 else -1.0
    return index, sign


def hashed_vector(text: str, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    for word in WORD_PATTERN.findall(text.lower()):
        index, sign = hashed_bucket(word, dimensions)
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        vector[0] = 1.0
        return vector
    return [value / norm for value in vector]


class FakeEmbedder:
    def __init__(
        self, dimensions: int = 1536, model: str = "fake-embedding", ledger: UsageLedger | None = None
    ) -> None:
        self._dimensions = dimensions
        self._model = model
        self._ledger = ledger

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: Sequence[str], context: CallContext) -> list[list[float]]:
        if self._ledger is not None and texts:
            usage = LlmUsage(
                provider="fake",
                model=self._model,
                input_tokens=sum(estimate_tokens(text) for text in texts),
                output_tokens=0,
                cached_input_tokens=0,
                cost_micros_usd=0,
            )
            await self._ledger.record(embed_context(context, 0), LlmTask.ROUTE, usage)
        return [hashed_vector(text, self._dimensions) for text in texts]
