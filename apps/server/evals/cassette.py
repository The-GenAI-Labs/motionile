import hashlib
import json
from collections import defaultdict, deque
from collections.abc import Mapping
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, JsonValue

from evals.errors import CassetteMissError
from motionile.engine.ai.llm.models import (
    ImageBlock,
    LlmCall,
    LlmClient,
    LlmResult,
    LlmTask,
    LlmUsage,
    UsageLedger,
)
from motionile.engine.ai.llm.usage import usage_context

CASSETTES_ROOT: Final = Path(__file__).parent / "cassettes"
CASSETTE_VERSION: Final = 1
HASH_PREFIX_CHARS: Final = 12
LINE_BREAK: Final = chr(10)


class RecordedUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    cost_micros_usd: int

    @classmethod
    def of(cls, usage: LlmUsage) -> "RecordedUsage":
        return cls(
            provider=usage.provider,
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            cost_micros_usd=usage.cost_micros_usd,
        )

    def usage(self) -> LlmUsage:
        return LlmUsage(
            provider=self.provider,
            model=self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cached_input_tokens=self.cached_input_tokens,
            cost_micros_usd=self.cost_micros_usd,
        )


class CassetteEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_hash: str
    task: LlmTask
    output: dict[str, JsonValue]
    usage: RecordedUsage


class Cassette(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = CASSETTE_VERSION
    namespace: str
    case: str
    entries: list[CassetteEntry]


def request_hash(call: LlmCall, output: type[BaseModel]) -> str:
    user: list[Mapping[str, str]] = [
        {"image": block.label} if isinstance(block, ImageBlock) else {"text": block} for block in call.user_blocks
    ]
    document = {
        "task": call.task.value,
        "output": output.__name__,
        "system": list(call.system_blocks),
        "user": user,
    }
    canonical = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CassetteStore:
    def __init__(self, root: Path = CASSETTES_ROOT) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def path(self, namespace: str, case: str) -> Path:
        return self._root / namespace / f"{case}.json"

    def load(self, namespace: str, case: str) -> Cassette:
        path = self.path(namespace, case)
        if not path.is_file():
            return Cassette(namespace=namespace, case=case, entries=[])
        return Cassette.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, cassette: Cassette) -> Path:
        path = self.path(cassette.namespace, cassette.case)
        path.parent.mkdir(parents=True, exist_ok=True)
        records = [entry.model_dump_json() for entry in cassette.entries]
        document = {"version": cassette.version, "namespace": cassette.namespace, "case": cassette.case}
        opening = json.dumps(document, separators=(",", ":"))[:-1] + ',"entries":['
        body = LINE_BREAK.join([opening, ("," + LINE_BREAK).join(records), "]}", ""])
        path.write_text(body, encoding="utf-8", newline=LINE_BREAK)
        return path


class CassetteLlm:
    def __init__(self, cassette: Cassette, ledger: UsageLedger) -> None:
        self._cassette = cassette
        self._ledger = ledger
        self._pending: dict[str, deque[CassetteEntry]] = defaultdict(deque)
        for entry in cassette.entries:
            self._pending[entry.request_hash].append(entry)

    async def generate[OutputT: BaseModel](self, call: LlmCall, output: type[OutputT]) -> LlmResult[OutputT]:
        digest = request_hash(call, output)
        queue = self._pending.get(digest)
        if not queue:
            raise CassetteMissError(
                f"no recording for a {call.task.value} call ({digest[:HASH_PREFIX_CHARS]}) "
                f"in {self._cassette.namespace}/{self._cassette.case}; re-record with --record"
            )
        entry = queue.popleft()
        usage = entry.usage.usage()
        await self._ledger.record(usage_context(call.context, usage.model, 0), call.task, usage)
        return LlmResult(output=output.model_validate(entry.output), usage=usage, attempts=1, fallback_used=False)


class RecordingLlm:
    def __init__(self, inner: LlmClient, namespace: str, case: str) -> None:
        self._inner = inner
        self._namespace = namespace
        self._case = case
        self._entries: list[CassetteEntry] = []

    async def generate[OutputT: BaseModel](self, call: LlmCall, output: type[OutputT]) -> LlmResult[OutputT]:
        result = await self._inner.generate(call, output)
        self._entries.append(
            CassetteEntry(
                request_hash=request_hash(call, output),
                task=call.task,
                output=result.output.model_dump(mode="json", by_alias=True),
                usage=RecordedUsage.of(result.usage),
            )
        )
        return result

    def cassette(self) -> Cassette:
        return Cassette(namespace=self._namespace, case=self._case, entries=list(self._entries))
