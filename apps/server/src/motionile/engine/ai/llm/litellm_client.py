import asyncio
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog
from pydantic import BaseModel, ValidationError

from motionile.engine.ai.llm import litellm_gateway as gateway
from motionile.engine.ai.llm.capabilities import provider_of, uses_explicit_cache_control, uses_native_schema
from motionile.engine.ai.llm.config import BudgetProvider, LlmClientConfig, RoutingProvider
from motionile.engine.ai.llm.litellm_gateway import FailureKind
from motionile.engine.ai.llm.models import (
    LlmCall,
    LlmError,
    LlmResult,
    LlmTimeoutError,
    LlmUnavailableError,
    LlmUsage,
    ModelOutputInvalidError,
    RouteConfig,
    Span,
    Tracer,
    UsageLedger,
)
from motionile.engine.ai.llm.prompt import (
    Message,
    build_messages,
    describe_validation_errors,
    json_candidate,
    reask_messages,
    response_format_for,
    schema_instruction,
    summarize_user_blocks,
)
from motionile.engine.ai.llm.redaction import trace_text
from motionile.engine.ai.llm.tracing import NoopTracer
from motionile.engine.ai.llm.usage import (
    BudgetGuard,
    combine_usage,
    estimate_blocks_tokens,
    estimate_tokens,
    usage_context,
)

logger = structlog.get_logger(__name__)

type Sleep = Callable[[float], Awaitable[None]]
type Jitter = Callable[[], float]


def secure_jitter() -> float:
    return secrets.SystemRandom().random()


class ModelFailedError(Exception):
    def __init__(self, kind: FailureKind) -> None:
        super().__init__(kind.value)
        self.kind = kind


@dataclass(slots=True)
class RunState:
    requests: int = 0


@dataclass(frozen=True, slots=True)
class Exchange:
    call: LlmCall
    output: type[BaseModel]
    route: RouteConfig
    input_tokens: int


@dataclass(frozen=True, slots=True)
class RoundPlan:
    index: int
    start: int
    extra: tuple[str, str] | None
    tokens: int


@dataclass(frozen=True, slots=True)
class RoundResult:
    text: str
    usage: LlmUsage
    model_index: int


class LiteLlmClient:
    def __init__(  # noqa: PLR0913
        self,
        *,
        routing: RoutingProvider,
        ledger: UsageLedger,
        budget: BudgetProvider,
        config: LlmClientConfig | None = None,
        tracer: Tracer | None = None,
        sleep: Sleep = asyncio.sleep,
        jitter: Jitter = secure_jitter,
    ) -> None:
        self._routing = routing
        self._ledger = ledger
        self._guard = BudgetGuard(ledger, budget)
        self._config = config or LlmClientConfig()
        self._tracer: Tracer = tracer or NoopTracer()
        self._sleep = sleep
        self._jitter = jitter

    async def generate[OutputT: BaseModel](self, call: LlmCall, output: type[OutputT]) -> LlmResult[OutputT]:
        route = (await self._routing.routing()).route(call.task)
        span = self._tracer.span(
            call.context, f"{call.task.value}.{call.context.stage}", trace_text(summarize_user_blocks(call.user_blocks))
        )
        try:
            result = await self._generate(call, output, route, span)
        except LlmError as error:
            span.fail(error.code.value)
            raise
        except BaseException:
            span.fail("unexpected_error")
            raise
        finally:
            span.end()
        return result

    async def _generate[OutputT: BaseModel](
        self, call: LlmCall, output: type[OutputT], route: RouteConfig, span: Span
    ) -> LlmResult[OutputT]:
        run = RunState()
        input_tokens = estimate_blocks_tokens(call.system_blocks, call.user_blocks, self._config.image_token_estimate)
        exchange = Exchange(call, output, route, input_tokens)
        first = await self._round(exchange, run, RoundPlan(index=0, start=0, extra=None, tokens=input_tokens))
        try:
            parsed = output.model_validate_json(json_candidate(first.text))
        except ValidationError as error:
            problems = describe_validation_errors(error)
        else:
            return self._finish(parsed, first, first.usage, run, span)
        retry_plan = RoundPlan(
            index=1,
            start=first.model_index,
            extra=(first.text, problems),
            tokens=input_tokens + estimate_tokens(first.text) + estimate_tokens(problems),
        )
        second = await self._round(exchange, run, retry_plan)
        usage = combine_usage(first.usage, second.usage)
        try:
            parsed = output.model_validate_json(json_candidate(second.text))
        except ValidationError:
            span.set_usage(usage)
            raise ModelOutputInvalidError from None
        return self._finish(parsed, second, usage, run, span)

    def _finish[OutputT: BaseModel](
        self, parsed: OutputT, last: RoundResult, usage: LlmUsage, run: RunState, span: Span
    ) -> LlmResult[OutputT]:
        span.set_usage(usage)
        span.set_output(trace_text(parsed.model_dump_json(by_alias=True)))
        return LlmResult(output=parsed, usage=usage, attempts=run.requests, fallback_used=last.model_index > 0)

    async def _round(self, exchange: Exchange, run: RunState, plan: RoundPlan) -> RoundResult:
        call = exchange.call
        route = exchange.route
        await self._guard.ensure(call.context, input_tokens=plan.tokens, max_output_tokens=route.max_output_tokens)
        failures: list[FailureKind] = []
        for index in range(plan.start, len(route.models)):
            model = route.models[index]
            try:
                completion = await self._attempt_model(exchange, model, plan.extra, run)
            except ModelFailedError as failure:
                failures.append(failure.kind)
                logger.warning("llm.model_failed", model=model, task=call.task.value, kind=failure.kind.value)
                continue
            usage = self._usage(model, completion, exchange)
            await self._ledger.record(usage_context(call.context, model, plan.index), call.task, usage)
            return RoundResult(text=completion.text, usage=usage, model_index=index)
        if failures and all(kind is FailureKind.TIMEOUT for kind in failures):
            raise LlmTimeoutError
        raise LlmUnavailableError

    def _usage(self, model: str, completion: gateway.Completion, exchange: Exchange) -> LlmUsage:
        input_tokens = completion.input_tokens
        if input_tokens is None:
            input_tokens = exchange.input_tokens
        output_tokens = completion.output_tokens
        if output_tokens is None:
            output_tokens = estimate_tokens(completion.text)
        return LlmUsage(
            provider=provider_of(model),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=completion.cached_tokens,
            cost_micros_usd=completion.cost_micros_usd,
        )

    def _messages(
        self, exchange: Exchange, model: str, extra: tuple[str, str] | None
    ) -> tuple[list[Message], dict[str, object] | None]:
        native = uses_native_schema(
            model,
            self._config.native_schema_providers,
            litellm_supports=gateway.supports_response_schema(model),
        )
        cache = uses_explicit_cache_control(model, self._config.explicit_cache_providers)
        instruction = None if native else schema_instruction(exchange.output)
        messages = build_messages(exchange.call, cache_control=cache, instruction=instruction)
        if extra is not None:
            messages = reask_messages(messages, extra[0], extra[1])
        return messages, response_format_for(exchange.output) if native else None

    async def _attempt_model(
        self, exchange: Exchange, model: str, extra: tuple[str, str] | None, run: RunState
    ) -> gateway.Completion:
        key = self._config.keys.for_provider(provider_of(model))
        if key is None:
            logger.warning("llm.provider_not_configured", model=model)
            raise ModelFailedError(FailureKind.PERMANENT)
        messages, response_format = self._messages(exchange, model, extra)
        route = exchange.route
        policy = self._config.retry
        attempt = 0
        while True:
            attempt += 1
            run.requests += 1
            try:
                async with asyncio.timeout(route.timeout_seconds + self._config.timeout_grace_seconds):
                    return await gateway.complete(
                        model=model,
                        messages=messages,
                        temperature=route.temperature,
                        max_tokens=route.max_output_tokens,
                        timeout_seconds=route.timeout_seconds,
                        api_key=key.get_secret_value(),
                        response_format=response_format,
                    )
            except Exception as error:
                kind = gateway.classify_failure(error)
                if kind is None:
                    raise
                logger.warning(
                    "llm.request_failed",
                    model=model,
                    task=exchange.call.task.value,
                    attempt=attempt,
                    kind=kind.value,
                    error=type(error).__name__,
                )
                if kind is FailureKind.PERMANENT or attempt == policy.attempts_per_model:
                    raise ModelFailedError(kind) from None
                await self._sleep(policy.delay(attempt, self._jitter()))
