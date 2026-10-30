from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from pydantic import SecretStr

from motionile.engine.ai.base import AiModel
from motionile.engine.ai.llm.config import LlmClientConfig, ProviderKeys, RetryPolicy
from motionile.engine.ai.llm.litellm_gateway import litellm
from motionile.engine.ai.llm.models import (
    CallContext,
    LlmCall,
    LlmTask,
    LlmUsage,
    RouteConfig,
    RoutingConfig,
    UserBlock,
)

FIXTURES_ROOT = Path(__file__).resolve().parents[4] / "fixtures" / "llm"
ANTHROPIC_MODEL = "anthropic/claude-sonnet-5-5"
ANTHROPIC_FALLBACK = "anthropic/claude-opus-5-5"
OPENAI_MODEL = "openai/gpt-4o-mini"
KEYS = ProviderKeys(anthropic=SecretStr("sk-ant-test-key-0123456789"), openai=SecretStr("sk-test-key-0123456789"))
FAST_RETRY = RetryPolicy(attempts_per_model=3, base_delay_seconds=1.0, max_delay_seconds=4.0)


class Answer(AiModel):
    title: str
    score: int


def routing_for(primary: str, *fallbacks: str) -> RoutingConfig:
    route = RouteConfig(primary=primary, fallbacks=list(fallbacks), timeout_seconds=30)
    return RoutingConfig(routes=dict.fromkeys(LlmTask, route))


def client_config() -> LlmClientConfig:
    return LlmClientConfig(keys=KEYS, retry=FAST_RETRY)


def context(job_id: UUID | None = None, call_key: str = "job:plan") -> CallContext:
    return CallContext(user_id=uuid4(), job_id=job_id, stage="plan", call_key=call_key)


def make_call(
    task: LlmTask = LlmTask.PLAN,
    *,
    call_context: CallContext | None = None,
    system: tuple[str, ...] = ("You are a planner.", "Skill: flow diagrams."),
    user: tuple[UserBlock, ...] = ("Explain DNS",),
    metadata: Mapping[str, str] | None = None,
) -> LlmCall:
    return LlmCall(
        task=task,
        context=call_context or context(),
        system_blocks=system,
        user_blocks=user,
        metadata=metadata or {},
    )


def completion(
    text: str, prompt_tokens: int = 100, completion_tokens: int = 20, cached: int = 0
) -> litellm.ModelResponse:
    usage = litellm.Usage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        prompt_tokens_details={"cached_tokens": cached},
    )
    return litellm.ModelResponse(
        choices=[litellm.Choices(message=litellm.Message(content=text), finish_reason="stop")],
        usage=usage,
    )


def valid_answer(title: str = "DNS", score: int = 5) -> str:
    return Answer(title=title, score=score).model_dump_json(by_alias=True)


class ScriptedCompletions:
    def __init__(self, steps: Sequence[litellm.ModelResponse | BaseException]) -> None:
        self.pending = list(steps)
        self.requests: list[dict[str, object]] = []

    async def __call__(self, **kwargs: object) -> litellm.ModelResponse:
        self.requests.append(kwargs)
        step = self.pending.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step

    @property
    def models(self) -> list[object]:
        return [request["model"] for request in self.requests]

    def messages(self, index: int = 0) -> list[dict[str, Any]]:
        return cast("list[dict[str, Any]]", self.requests[index]["messages"])


@dataclass
class Sleeps:
    delays: list[float] = field(default_factory=list[float])

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def half_jitter() -> float:
    return 0.5


@dataclass
class RecordingSpan:
    outputs: list[str] = field(default_factory=list[str])
    usages: list[LlmUsage] = field(default_factory=list[LlmUsage])
    failures: list[str] = field(default_factory=list[str])
    ended: int = 0

    def set_output(self, summary: str) -> None:
        self.outputs.append(summary)

    def set_usage(self, usage: LlmUsage) -> None:
        self.usages.append(usage)

    def fail(self, code: str) -> None:
        self.failures.append(code)

    def end(self) -> None:
        self.ended += 1


@dataclass
class RecordingTracer:
    spans: list[tuple[str, str, RecordingSpan]] = field(default_factory=list[tuple[str, str, RecordingSpan]])

    def span(self, context: CallContext, name: str, summary: str) -> RecordingSpan:
        del context
        span = RecordingSpan()
        self.spans.append((name, summary, span))
        return span
