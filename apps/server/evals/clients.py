from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from evals.cassette import CassetteLlm, CassetteStore, RecordingLlm
from evals.datasets import Datasets
from evals.errors import EvalAbortError, ProviderKeysMissingError
from evals.judge import Judge
from evals.metering import MeteredLlm, SpendLedger, SpendMeter
from evals.modes import RunMode
from evals.scripted import JOB_TOKEN_BUDGET, ScriptedLlm
from motionile.engine.ai.llm.config import LlmClientConfig, ProviderKeys, RoutingProvider, StaticBudget, StaticRouting
from motionile.engine.ai.llm.embeddings import EmbedderConfig, FakeEmbedder, LiteLlmEmbedder
from motionile.engine.ai.llm.litellm_client import LiteLlmClient
from motionile.engine.ai.llm.models import Embedder, LlmClient
from motionile.engine.ai.llm.routing import DEFAULT_ROUTING

SERVER_ROOT: Final = Path(__file__).resolve().parents[1]
FIXTURES_ROOT: Final = SERVER_ROOT / "tests" / "fixtures" / "llm"
FAKE_EMBEDDING_DIMENSIONS: Final = 256
DEFAULT_EMBEDDING_MODEL: Final = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIMENSIONS: Final = 1_536
ANTHROPIC_VARIABLE: Final = "AI_ANTHROPIC_API_KEY"
OPENAI_VARIABLE: Final = "OPENAI_API_KEY"


@dataclass(frozen=True, slots=True)
class LiveSettings:
    keys: ProviderKeys
    routing: RoutingProvider = field(default_factory=lambda: StaticRouting(DEFAULT_ROUTING))
    job_token_budget: int = JOB_TOKEN_BUDGET
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS

    @property
    def has_keys(self) -> bool:
        return self.keys.anthropic is not None and self.keys.openai is not None

    def require_keys(self) -> None:
        missing = [
            variable
            for variable, key in ((ANTHROPIC_VARIABLE, self.keys.anthropic), (OPENAI_VARIABLE, self.keys.openai))
            if key is None
        ]
        if missing:
            raise ProviderKeysMissingError(f"live mode needs provider keys, missing: {', '.join(missing)}")


@dataclass(slots=True)
class CaseSession:
    llm: LlmClient
    ledger: SpendLedger
    embedder: Embedder
    judge: Judge | None


class LlmSessions:
    def __init__(  # noqa: PLR0913
        self,
        *,
        mode: RunMode,
        meter: SpendMeter,
        datasets: Datasets,
        cassettes: CassetteStore,
        record: bool = False,
        live: LiveSettings | None = None,
        fixtures_root: Path = FIXTURES_ROOT,
    ) -> None:
        if mode is RunMode.AUTO:
            raise ValueError("a session factory needs a concrete mode")
        if mode is RunMode.LIVE:
            if live is None:
                raise ProviderKeysMissingError("live mode needs provider settings")
            live.require_keys()
        self._mode = mode
        self._meter = meter
        self._datasets = datasets
        self._cassettes = cassettes
        self._record = record
        self._live = live
        self._fixtures_root = fixtures_root

    @property
    def mode(self) -> RunMode:
        return self._mode

    @property
    def meter(self) -> SpendMeter:
        return self._meter

    def _scripted(self, ledger: SpendLedger) -> LlmClient:
        if not self._fixtures_root.is_dir():
            raise EvalAbortError(f"the scripted fixtures are missing at {self._fixtures_root}")
        return ScriptedLlm(fixtures_root=self._fixtures_root, ledger=ledger, datasets=self._datasets)

    def _live_client(self, ledger: SpendLedger) -> LlmClient:
        live = self._require_live()
        return LiteLlmClient(
            routing=live.routing,
            ledger=ledger,
            budget=StaticBudget(live.job_token_budget),
            config=LlmClientConfig(keys=live.keys),
        )

    def _require_live(self) -> LiveSettings:
        if self._live is None:
            raise ProviderKeysMissingError("live mode needs provider settings")
        return self._live

    def _embedder(self, ledger: SpendLedger) -> Embedder:
        if self._mode is not RunMode.LIVE:
            return FakeEmbedder(dimensions=FAKE_EMBEDDING_DIMENSIONS)
        live = self._require_live()
        config = EmbedderConfig.with_keys(live.embedding_model, live.embedding_dimensions, live.keys)
        return LiteLlmEmbedder(config, ledger)

    @asynccontextmanager
    async def open(self, namespace: str, case_id: str) -> AsyncGenerator[CaseSession]:
        ledger = SpendLedger(self._meter)
        recorder: RecordingLlm | None = None
        source: LlmClient
        if self._mode is RunMode.LIVE:
            source = self._live_client(ledger)
        elif self._mode is RunMode.DETERMINISTIC or self._record:
            source = self._scripted(ledger)
        else:
            source = CassetteLlm(self._cassettes.load(namespace, case_id), ledger)
        if self._record and self._mode is not RunMode.DETERMINISTIC:
            recorder = RecordingLlm(source, namespace, case_id)
            source = recorder
        llm: LlmClient = MeteredLlm(source, self._meter)
        judge = None if self._mode is RunMode.DETERMINISTIC else Judge(llm)
        yield CaseSession(llm=llm, ledger=ledger, embedder=self._embedder(ledger), judge=judge)
        if recorder is not None:
            self._cassettes.save(recorder.cassette())
