from dataclasses import dataclass, field
from pathlib import Path

from motionile.engine.ai.llm.config import BudgetProvider, LlmClientConfig, RoutingProvider
from motionile.engine.ai.llm.fake import FakeLlm, FakeScript
from motionile.engine.ai.llm.litellm_client import LiteLlmClient
from motionile.engine.ai.llm.models import LlmClient, Tracer, UsageLedger
from motionile.engine.ai.llm.tracing import NoopTracer


@dataclass(frozen=True, slots=True)
class FakeLlmConfig:
    fixtures_root: Path
    script: FakeScript = field(default_factory=FakeScript)


def build_llm_client(  # noqa: PLR0913
    *,
    use_fake: bool,
    routing: RoutingProvider,
    ledger: UsageLedger,
    budget: BudgetProvider,
    tracer: Tracer | None = None,
    config: LlmClientConfig | None = None,
    fake: FakeLlmConfig | None = None,
) -> LlmClient:
    active_tracer = tracer or NoopTracer()
    if use_fake:
        if fake is None:
            raise ValueError("the fake LLM client needs a fixtures root")
        return FakeLlm(
            fixtures_root=fake.fixtures_root,
            ledger=ledger,
            budget=budget,
            script=fake.script,
            routing=routing,
            tracer=active_tracer,
        )
    return LiteLlmClient(routing=routing, ledger=ledger, budget=budget, config=config, tracer=active_tracer)
