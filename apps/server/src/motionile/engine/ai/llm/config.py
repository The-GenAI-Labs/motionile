from dataclasses import dataclass, field
from typing import Protocol

from pydantic import SecretStr

from motionile.engine.ai.llm.models import RoutingConfig


class RoutingProvider(Protocol):
    async def routing(self) -> RoutingConfig: ...


class BudgetProvider(Protocol):
    async def job_token_budget(self) -> int: ...


@dataclass(frozen=True, slots=True)
class StaticRouting:
    config: RoutingConfig

    async def routing(self) -> RoutingConfig:
        return self.config


@dataclass(frozen=True, slots=True)
class StaticBudget:
    tokens: int

    async def job_token_budget(self) -> int:
        return self.tokens


@dataclass(frozen=True, slots=True)
class ProviderKeys:
    anthropic: SecretStr | None = field(default=None, repr=False)
    openai: SecretStr | None = field(default=None, repr=False)

    def for_provider(self, provider: str) -> SecretStr | None:
        if provider == "anthropic":
            return self.anthropic
        if provider == "openai":
            return self.openai
        return None


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    attempts_per_model: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0

    def delay(self, attempt: int, jitter: float) -> float:
        ceiling = min(self.base_delay_seconds * 2 ** (attempt - 1), self.max_delay_seconds)
        return ceiling * (0.5 + 0.5 * jitter)


@dataclass(frozen=True, slots=True)
class LlmClientConfig:
    keys: ProviderKeys = field(default_factory=ProviderKeys)
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    timeout_grace_seconds: float = 5.0
    image_token_estimate: int = 1_600
    native_schema_providers: frozenset[str] = frozenset({"openai"})
    explicit_cache_providers: frozenset[str] = frozenset({"anthropic"})
