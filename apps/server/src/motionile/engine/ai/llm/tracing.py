import hashlib
from dataclasses import dataclass, field
from typing import Protocol, cast
from uuid import UUID

import structlog
from langfuse import Langfuse
from langfuse.types import TraceContext
from pydantic import SecretStr

from motionile.engine.ai.llm.models import CallContext, LlmUsage, Span
from motionile.engine.ai.llm.redaction import redact_value, trace_text

logger = structlog.get_logger(__name__)

MICROS_PER_USD = 1_000_000
TRACE_ID_BYTES = 16


class Observation(Protocol):
    def update(self, **fields: object) -> object: ...

    def end(self) -> object: ...


class NoopSpan:
    def set_output(self, summary: str) -> None:  # noqa: ARG002
        return None

    def set_usage(self, usage: LlmUsage) -> None:  # noqa: ARG002
        return None

    def fail(self, code: str) -> None:  # noqa: ARG002
        return None

    def end(self) -> None:
        return None


class NoopTracer:
    def span(self, context: CallContext, name: str, summary: str) -> Span:  # noqa: ARG002
        return NoopSpan()


def job_trace_id(job_id: UUID) -> str:
    return hashlib.sha256(str(job_id).encode("utf-8")).digest()[:TRACE_ID_BYTES].hex()


def trace_link(host: str, project_id: str | None, trace_id: str) -> str | None:
    if not project_id or not trace_id:
        return None
    return f"{host.rstrip('/')}/project/{project_id}/traces/{trace_id}"


@dataclass(frozen=True, slots=True)
class LangfuseConfig:
    public_key: SecretStr = field(repr=False)
    secret_key: SecretStr = field(repr=False)
    host: str
    environment: str | None = None


def mask_secrets(*, data: object, **_options: object) -> object:
    return redact_value(data)


def create_langfuse_client(config: LangfuseConfig) -> Langfuse:
    return Langfuse(
        public_key=config.public_key.get_secret_value(),
        secret_key=config.secret_key.get_secret_value(),
        host=config.host,
        environment=config.environment,
        mask=mask_secrets,
    )


class LangfuseSpan:
    def __init__(self, observation: object) -> None:
        self._observation = observation

    def set_output(self, summary: str) -> None:
        self._update(output=trace_text(summary))

    def set_usage(self, usage: LlmUsage) -> None:
        self._update(
            model=usage.model,
            usage_details={
                "input": usage.input_tokens,
                "output": usage.output_tokens,
                "cache_read_input_tokens": usage.cached_input_tokens,
            },
            cost_details={"total": usage.cost_micros_usd / MICROS_PER_USD},
        )

    def fail(self, code: str) -> None:
        self._update(level="ERROR", status_message=code)

    def end(self) -> None:
        try:
            cast("Observation", self._observation).end()
        except Exception:
            logger.warning("llm.trace_failed", operation="end")

    def _update(self, **fields: object) -> None:
        try:
            cast("Observation", self._observation).update(**fields)
        except Exception:
            logger.warning("llm.trace_failed", operation="update")


class LangfuseTracer:
    def __init__(self, client: Langfuse) -> None:
        self._client = client

    def span(self, context: CallContext, name: str, summary: str) -> Span:
        try:
            trace_context = TraceContext(trace_id=job_trace_id(context.job_id)) if context.job_id is not None else None
            observation = self._client.start_observation(
                trace_context=trace_context,
                name=name,
                as_type="generation",
                input=trace_text(summary),
                metadata={"stage": context.stage},
            )
        except Exception:
            logger.warning("llm.trace_failed", operation="start")
            return NoopSpan()
        return LangfuseSpan(observation)

    def flush(self) -> None:
        try:
            self._client.flush()
        except Exception:
            logger.warning("llm.trace_failed", operation="flush")

    def shutdown(self) -> None:
        try:
            self._client.shutdown()
        except Exception:
            logger.warning("llm.trace_failed", operation="shutdown")
