import os
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, cast

import structlog

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

import litellm

logger = structlog.get_logger(__name__)

READ_ONLY_WARNING = r".*is using the `ReadOnly` qualifier.*"
PYDANTIC_SCHEMA_MODULE = r"pydantic\._internal\._generate_schema"


def build_response_models_quietly() -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message=READ_ONLY_WARNING, category=UserWarning, module=PYDANTIC_SCHEMA_MODULE
        )
        message = litellm.Message(content="")
        litellm.ModelResponse(choices=[litellm.Choices(message=message)], usage=litellm.Usage(prompt_tokens=0))
        litellm.EmbeddingResponse(model="warm-up", data=[], usage=litellm.Usage(prompt_tokens=0))


build_response_models_quietly()

SERVER_ERROR_FLOOR: Final = 500
MICROS_PER_USD: Final = 1_000_000


class FailureKind(StrEnum):
    TIMEOUT = "timeout"
    TRANSIENT = "transient"
    PERMANENT = "permanent"


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    finish_reason: str | None
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int
    cost_micros_usd: int


@dataclass(frozen=True, slots=True)
class EmbeddingCompletion:
    vectors: list[list[float]]
    input_tokens: int | None
    cost_micros_usd: int


class UnusableResponseError(Exception):
    pass


def classify_failure(error: BaseException) -> FailureKind | None:
    if isinstance(error, TimeoutError | litellm.exceptions.Timeout):
        return FailureKind.TIMEOUT
    if isinstance(
        error,
        litellm.exceptions.RateLimitError
        | litellm.exceptions.InternalServerError
        | litellm.exceptions.ServiceUnavailableError
        | litellm.exceptions.BadGatewayError
        | litellm.exceptions.APIConnectionError,
    ):
        return FailureKind.TRANSIENT
    if isinstance(error, litellm.exceptions.APIError):
        status = cast("int | None", getattr(error, "status_code", None))
        return FailureKind.TRANSIENT if status is not None and status >= SERVER_ERROR_FLOOR else FailureKind.PERMANENT
    if isinstance(
        error,
        litellm.exceptions.AuthenticationError
        | litellm.exceptions.NotFoundError
        | litellm.exceptions.BadRequestError
        | litellm.exceptions.PermissionDeniedError
        | litellm.exceptions.UnprocessableEntityError
        | UnusableResponseError,
    ):
        return FailureKind.PERMANENT
    return None


def supports_response_schema(model: str) -> bool:
    try:
        return bool(litellm.supports_response_schema(model=model))
    except Exception:
        logger.warning("llm.capability_lookup_failed", model=model)
        return False


def cost_in_micros(response: object, model: str, *, call_type: str | None = None) -> int:
    try:
        cost = float(litellm.completion_cost(completion_response=response, model=model, call_type=call_type))
    except Exception:
        logger.warning("llm.cost_unknown", model=model)
        return 0
    return round(cost * MICROS_PER_USD)


def int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def cached_tokens_of(usage: object) -> int:
    details = getattr(usage, "prompt_tokens_details", None)
    cached = int_or_none(getattr(details, "cached_tokens", None))
    return cached or 0


async def complete(  # noqa: PLR0913
    *,
    model: str,
    messages: Sequence[Mapping[str, object]],
    temperature: float,
    max_tokens: int,
    timeout_seconds: float,
    api_key: str,
    response_format: Mapping[str, object] | None,
) -> Completion:
    response = await litellm.acompletion(
        model=model,
        messages=[dict(message) for message in messages],
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout_seconds,
        api_key=api_key,
        response_format=dict(response_format) if response_format is not None else None,
        stream=False,
        num_retries=0,
        max_retries=0,
        drop_params=True,
    )
    if not isinstance(response, litellm.ModelResponse) or not response.choices:
        raise UnusableResponseError("the provider returned no completion")
    choice = response.choices[0]
    content: str | None = choice.message.content
    usage = cast("object", getattr(response, "usage", None))
    return Completion(
        text=content or "",
        finish_reason=cast("str | None", choice.finish_reason),
        input_tokens=int_or_none(getattr(usage, "prompt_tokens", None)),
        output_tokens=int_or_none(getattr(usage, "completion_tokens", None)),
        cached_tokens=cached_tokens_of(usage),
        cost_micros_usd=cost_in_micros(response, model),
    )


def embedding_vector(item: object) -> list[float]:
    raw: object = (
        cast("dict[str, object]", item).get("embedding") if isinstance(item, dict) else getattr(item, "embedding", None)
    )
    return [float(value) for value in cast("Sequence[float]", raw)]


async def embed(
    *, model: str, texts: Sequence[str], dimensions: int, timeout_seconds: float, api_key: str
) -> EmbeddingCompletion:
    response = await litellm.aembedding(
        model=model,
        input=list(texts),
        dimensions=dimensions,
        timeout=timeout_seconds,
        api_key=api_key,
        max_retries=0,
        num_retries=0,
    )
    items = cast("list[object]", getattr(response, "data", []))
    if len(items) != len(texts):
        raise UnusableResponseError("the provider returned the wrong number of embeddings")
    usage = cast("object", getattr(response, "usage", None))
    return EmbeddingCompletion(
        vectors=[embedding_vector(item) for item in items],
        input_tokens=int_or_none(getattr(usage, "prompt_tokens", None)),
        cost_micros_usd=cost_in_micros(response, model, call_type="aembedding"),
    )
