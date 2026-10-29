from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import BaseModel

from evals.cassette import (
    Cassette,
    CassetteEntry,
    CassetteLlm,
    CassetteStore,
    RecordedUsage,
    RecordingLlm,
    request_hash,
)
from evals.errors import CassetteMissError
from evals.metering import SpendLedger, SpendMeter
from motionile.engine.ai.guardrails.decision import GuardDecision
from motionile.engine.ai.guardrails.policy import PolicyCode
from motionile.engine.ai.llm.models import (
    CallContext,
    ImageBlock,
    LlmCall,
    LlmResult,
    LlmTask,
    LlmUsage,
)

USAGE = LlmUsage("fake", "fake/guard", 10, 5, 0, 0)


def call(text: str = "hello", *, system: str = "rules", task: LlmTask = LlmTask.GUARD, key: str = "k") -> LlmCall:
    context = CallContext(user_id=uuid4(), job_id=uuid4(), stage="guard", call_key=key)
    return LlmCall(task=task, context=context, system_blocks=[system], user_blocks=[text])


class FixedLlm:
    def __init__(self, *answers: GuardDecision) -> None:
        self._answers = list(answers)
        self.calls = 0

    async def generate[OutputT: BaseModel](self, call: LlmCall, output: type[OutputT]) -> LlmResult[OutputT]:
        del call
        self.calls += 1
        answer = self._answers.pop(0)
        return LlmResult(
            output=output.model_validate(answer.model_dump(by_alias=True)), usage=USAGE, attempts=1, fallback_used=False
        )


ALLOW = GuardDecision(verdict="allow", reason="fine")
REFUSE = GuardDecision(verdict="refuse", code=PolicyCode.WEAPONS, reason="no")


def test_the_hash_ignores_identity_and_changes_with_every_model_visible_part() -> None:
    base = request_hash(call(), GuardDecision)

    assert request_hash(call(key="another"), GuardDecision) == base
    assert request_hash(call("different"), GuardDecision) != base
    assert request_hash(call(system="other rules"), GuardDecision) != base
    assert request_hash(call(task=LlmTask.PLAN), GuardDecision) != base


def test_images_are_identified_by_their_label_not_their_bytes() -> None:
    first = LlmCall(LlmTask.VISION_REVIEW, call().context, ["s"], [ImageBlock(b"one", "scene a, 16:9, 1.00s")])
    second = LlmCall(LlmTask.VISION_REVIEW, call().context, ["s"], [ImageBlock(b"two", "scene a, 16:9, 1.00s")])
    third = LlmCall(LlmTask.VISION_REVIEW, call().context, ["s"], [ImageBlock(b"one", "scene b, 16:9, 1.00s")])

    assert request_hash(first, GuardDecision) == request_hash(second, GuardDecision)
    assert request_hash(first, GuardDecision) != request_hash(third, GuardDecision)


async def test_a_call_without_a_recording_fails_closed_with_cassette_miss() -> None:
    replay = CassetteLlm(Cassette(namespace="safety", case="inj-direct-01", entries=[]), SpendLedger(SpendMeter()))

    with pytest.raises(CassetteMissError, match="safety/inj-direct-01"):
        await replay.generate(call(), GuardDecision)


async def test_the_error_code_of_a_miss_is_cassette_miss() -> None:
    assert CassetteMissError.code == "cassette_miss"


async def test_recording_then_replaying_returns_the_same_answers_and_usage(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path)
    recorder = RecordingLlm(FixedLlm(ALLOW, REFUSE), "safety", "case-1")
    first = await recorder.generate(call("one"), GuardDecision)
    second = await recorder.generate(call("two"), GuardDecision)
    store.save(recorder.cassette())

    ledger = SpendLedger(SpendMeter())
    replay = CassetteLlm(store.load("safety", "case-1"), ledger)
    replayed_second = await replay.generate(call("two", key="x"), GuardDecision)
    replayed_first = await replay.generate(call("one", key="y"), GuardDecision)

    assert replayed_first.output == first.output
    assert replayed_second.output == second.output
    assert replayed_first.usage == USAGE
    assert len(ledger.records) == 2


async def test_identical_requests_replay_their_recordings_in_order_then_miss() -> None:
    cassette = Cassette(
        namespace="n",
        case="c",
        entries=[
            CassetteEntry(
                request_hash=request_hash(call(), GuardDecision),
                task=LlmTask.GUARD,
                output=answer.model_dump(mode="json", by_alias=True),
                usage=RecordedUsage.of(USAGE),
            )
            for answer in (ALLOW, REFUSE)
        ],
    )
    replay = CassetteLlm(cassette, SpendLedger(SpendMeter()))

    first = await replay.generate(call(key="a"), GuardDecision)
    second = await replay.generate(call(key="b"), GuardDecision)

    assert (first.output.verdict, second.output.verdict) == ("allow", "refuse")
    with pytest.raises(CassetteMissError):
        await replay.generate(call(key="c"), GuardDecision)


def test_a_missing_cassette_file_loads_as_an_empty_cassette(tmp_path: Path) -> None:
    assert CassetteStore(tmp_path).load("planner", "nope").entries == []


def test_a_saved_cassette_is_valid_json_with_one_entry_per_line(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path)
    entry = CassetteEntry(
        request_hash="h",
        task=LlmTask.GUARD,
        output=ALLOW.model_dump(mode="json", by_alias=True),
        usage=RecordedUsage.of(USAGE),
    )

    path = store.save(Cassette(namespace="safety", case="c", entries=[entry, entry]))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    assert store.load("safety", "c").entries == [entry, entry]
