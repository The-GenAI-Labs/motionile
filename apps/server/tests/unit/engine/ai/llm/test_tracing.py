from unittest.mock import MagicMock
from uuid import uuid4

from langfuse import Langfuse
from tests.unit.engine.ai.llm.support import context

from motionile.engine.ai.llm.models import LlmUsage
from motionile.engine.ai.llm.tracing import (
    LangfuseTracer,
    NoopTracer,
    job_trace_id,
    mask_secrets,
    trace_link,
)

USAGE = LlmUsage("anthropic", "anthropic/claude-sonnet-5-5", 120, 30, 80, 4_500)


def tracer_with(client: MagicMock) -> LangfuseTracer:
    return LangfuseTracer(client)


def test_every_span_of_a_job_joins_the_same_trace() -> None:
    client = MagicMock(spec=Langfuse)
    job_id = uuid4()
    tracer = tracer_with(client)

    tracer.span(context(job_id), "plan.plan", "Explain DNS")
    tracer.span(context(job_id), "critique.critique", "Check it")

    traces = [call.kwargs["trace_context"]["trace_id"] for call in client.start_observation.call_args_list]
    assert traces[0] == traces[1] == job_trace_id(job_id)
    assert traces[0] == Langfuse.create_trace_id(seed=str(job_id))


def test_spans_of_different_jobs_use_different_traces() -> None:
    assert job_trace_id(uuid4()) != job_trace_id(uuid4())


def test_a_call_without_a_job_starts_its_own_trace() -> None:
    client = MagicMock(spec=Langfuse)

    tracer_with(client).span(context(None), "guard.guard", "x")

    assert client.start_observation.call_args.kwargs["trace_context"] is None


def test_span_input_is_redacted_and_named() -> None:
    client = MagicMock(spec=Langfuse)

    tracer_with(client).span(context(uuid4()), "plan.plan", "mail me at someone@example.com please")

    kwargs = client.start_observation.call_args.kwargs
    assert kwargs["name"] == "plan.plan"
    assert kwargs["as_type"] == "generation"
    assert "someone@example.com" not in kwargs["input"]
    assert kwargs["metadata"] == {"stage": "plan"}


def test_usage_output_failure_and_end_reach_the_observation() -> None:
    client = MagicMock(spec=Langfuse)
    observation = client.start_observation.return_value
    span = tracer_with(client).span(context(uuid4()), "plan.plan", "q")

    span.set_usage(USAGE)
    span.set_output("answer for someone@example.com")
    span.fail("llm_unavailable")
    span.end()

    usage_call, output_call, fail_call = observation.update.call_args_list
    assert usage_call.kwargs["model"] == "anthropic/claude-sonnet-5-5"
    assert usage_call.kwargs["usage_details"] == {"input": 120, "output": 30, "cache_read_input_tokens": 80}
    assert usage_call.kwargs["cost_details"] == {"total": 0.0045}
    assert "someone@example.com" not in output_call.kwargs["output"]
    assert fail_call.kwargs == {"level": "ERROR", "status_message": "llm_unavailable"}
    observation.end.assert_called_once_with()


def test_tracing_failures_are_swallowed() -> None:
    client = MagicMock(spec=Langfuse)
    client.start_observation.side_effect = RuntimeError("langfuse is down")
    client.flush.side_effect = RuntimeError("down")
    client.shutdown.side_effect = RuntimeError("down")
    tracer = tracer_with(client)

    span = tracer.span(context(uuid4()), "plan.plan", "q")
    span.set_usage(USAGE)
    span.set_output("x")
    span.fail("code")
    span.end()
    tracer.flush()
    tracer.shutdown()


def test_observation_failures_are_swallowed() -> None:
    client = MagicMock(spec=Langfuse)
    observation = client.start_observation.return_value
    observation.update.side_effect = RuntimeError("down")
    observation.end.side_effect = RuntimeError("down")
    span = tracer_with(client).span(context(uuid4()), "plan.plan", "q")

    span.set_usage(USAGE)
    span.fail("code")
    span.end()


def test_flush_and_shutdown_are_forwarded() -> None:
    client = MagicMock(spec=Langfuse)
    tracer = tracer_with(client)

    tracer.flush()
    tracer.shutdown()

    client.flush.assert_called_once_with()
    client.shutdown.assert_called_once_with()


def test_the_noop_tracer_accepts_everything() -> None:
    span = NoopTracer().span(context(), "plan.plan", "q")

    span.set_usage(USAGE)
    span.set_output("x")
    span.fail("code")
    span.end()


def test_the_langfuse_mask_redacts_secrets_in_payloads() -> None:
    masked = mask_secrets(data={"input": "Authorization: Bearer abcdefgh12345678", "n": 1})

    assert masked == {"input": "Authorization: [redacted] [redacted]", "n": 1}


def test_trace_links_point_at_the_langfuse_project() -> None:
    trace_id = job_trace_id(uuid4())

    assert trace_link("https://cloud.langfuse.com/", "proj_1", trace_id) == (
        f"https://cloud.langfuse.com/project/proj_1/traces/{trace_id}"
    )
    assert trace_link("https://cloud.langfuse.com", None, trace_id) is None
    assert trace_link("https://cloud.langfuse.com", "proj_1", "") is None
