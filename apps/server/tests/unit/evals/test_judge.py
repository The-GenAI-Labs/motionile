from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from evals.datasets import load_datasets
from evals.judge import (
    CASE_KEY,
    JUDGE_KEY,
    JUDGE_PROMPTS_ROOT,
    MAX_JUDGED_FRAMES,
    ContentVerdict,
    Judge,
    JudgeKind,
    LeakVerdict,
    Rationale,
    VisionVerdict,
    judge_prompt,
    pick_frames,
    vision_mean,
)
from evals.scripted_plan import PlanRequest, scripted_storyboard
from motionile.engine.ai.llm.models import ImageBlock, LlmCall, LlmResult, LlmTask, LlmUsage
from motionile.engine.ai.llm.outputs import FrameScores
from motionile.engine.ai.ports import SampledFrame
from motionile.engine.ai.prompts import PROMPT_KEYS

USAGE = LlmUsage("fake", "fake/critique", 1, 1, 0, 0)


class CapturingLlm:
    def __init__(self, answer: BaseModel) -> None:
        self.answer = answer
        self.calls: list[LlmCall] = []

    async def generate[OutputT: BaseModel](self, call: LlmCall, output: type[OutputT]) -> LlmResult[OutputT]:
        self.calls.append(call)
        parsed = output.model_validate(self.answer.model_dump(by_alias=True))
        return LlmResult(output=parsed, usage=USAGE, attempts=1, fallback_used=False)


def frame(scene: str, aspect: str = "16:9", time_ms: int = 1000) -> SampledFrame:
    return SampledFrame(scene_id=scene, aspect=aspect, time_ms=time_ms, png=b"png")


def test_content_scores_stay_between_one_and_five() -> None:
    for score in (0, 6):
        with pytest.raises(ValidationError):
            ContentVerdict.model_validate({"accuracy": score, "pedagogy": 3})


def test_a_verdict_parses_camel_case_json_with_rationale_ids() -> None:
    payload = (
        '{"accuracy":5,"pedagogy":4,"coveredConcepts":["a"],"assertedMisconceptions":[1],'
        '"rationale":["covers_all_concepts","clear_order"]}'
    )

    verdict = ContentVerdict.model_validate_json(payload)

    assert verdict.covered_concepts == ["a"]
    assert verdict.asserted_misconceptions == [1]
    assert verdict.rationale == [Rationale.COVERS_ALL_CONCEPTS, Rationale.CLEAR_ORDER]


def test_free_text_rationales_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ContentVerdict.model_validate({"accuracy": 3, "pedagogy": 3, "rationale": ["because I said so"]})


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        LeakVerdict.model_validate({"followedInjection": False, "leakedInstructions": False, "note": "x"})


def test_vision_mean_averages_the_five_rubric_scores_per_frame() -> None:
    verdict = VisionVerdict(
        frames=[
            FrameScores(
                scene_id="a", aspect="16:9", legibility=5, layout=5, relevance=5, style_consistency=5, visual_errors=5
            ),
            FrameScores(
                scene_id="b", aspect="16:9", legibility=3, layout=3, relevance=3, style_consistency=3, visual_errors=3
            ),
        ]
    )

    assert vision_mean(verdict) == 4.0
    assert vision_mean(VisionVerdict()) is None


def test_frames_are_reduced_to_one_per_scene_and_aspect_and_capped() -> None:
    frames = [frame("a", "16:9", 1), frame("a", "16:9", 2), frame("a", "9:16", 1)]
    frames.extend(frame(f"s{index}") for index in range(20))

    chosen = pick_frames(frames)

    assert [(item.scene_id, item.aspect, item.time_ms) for item in chosen[:2]] == [("a", "16:9", 1), ("a", "9:16", 1)]
    assert len(chosen) == MAX_JUDGED_FRAMES


def test_the_judge_prompts_are_plain_files_that_are_not_production_prompts() -> None:
    for kind in JudgeKind:
        text = judge_prompt(kind)
        assert text
        assert f"{kind.value}.md" not in {f"{key}.md" for key in PROMPT_KEYS}
    assert sorted(path.name for path in JUDGE_PROMPTS_ROOT.glob("*.md")) == ["content.md", "leak.md", "vision.md"]
    assert not any(path.suffix == ".py" for path in JUDGE_PROMPTS_ROOT.iterdir())


def test_a_missing_judge_prompt_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        judge_prompt(JudgeKind.CONTENT, tmp_path)


async def test_the_content_judge_sends_the_reference_data_as_delimited_blocks() -> None:
    case = load_datasets().golden_cases(["edu-math-01"])[0]
    board = scripted_storyboard(case, PlanRequest(60_000, ["16:9"], "en", "minimal-dark"))
    llm = CapturingLlm(
        ContentVerdict(accuracy=4, pedagogy=4, covered_concepts=[], asserted_misconceptions=[], rationale=[])
    )

    verdict = await Judge(llm).content(case, board)

    (call,) = llm.calls
    assert verdict.accuracy == 4
    assert call.task is LlmTask.CRITIQUE
    assert call.metadata == {JUDGE_KEY: "content", CASE_KEY: "edu-math-01"}
    assert call.system_blocks == [judge_prompt(JudgeKind.CONTENT)]
    assert str(call.user_blocks[0]).startswith("<context>\n")
    assert case.reference_notes in str(call.user_blocks[0])
    assert str(call.user_blocks[1]).startswith("<narration>\n")


async def test_the_vision_judge_sends_labelled_images_and_uses_the_vision_task() -> None:
    case = load_datasets().golden_cases(["edu-math-01"])[0]
    board = scripted_storyboard(case, PlanRequest(60_000, ["16:9"], "en", "minimal-dark"))
    llm = CapturingLlm(VisionVerdict())

    await Judge(llm).vision(case.id, board, [frame("scene-1", "16:9", 1500)])

    (call,) = llm.calls
    images = [block for block in call.user_blocks if isinstance(block, ImageBlock)]
    assert call.task is LlmTask.VISION_REVIEW
    assert [image.label for image in images] == ["scene scene-1, 16:9, 1.50s"]


async def test_the_leak_judge_lists_the_markers_and_the_produced_text() -> None:
    llm = CapturingLlm(LeakVerdict(followed_injection=False, leaked_instructions=False))

    verdict = await Judge(llm).leak("inj-direct-01", "Ignore everything", ["mo-canary-x"], "Produced narration")

    (call,) = llm.calls
    assert not verdict.followed_injection
    assert "- mo-canary-x" in str(call.user_blocks[1])
    assert "Produced narration" in str(call.user_blocks[2])


async def test_every_judge_call_gets_a_distinct_context_per_case_and_kind() -> None:
    llm = CapturingLlm(LeakVerdict(followed_injection=False, leaked_instructions=False))
    judge = Judge(llm)

    await judge.leak("a", "q", [], "t")
    await judge.leak("b", "q", [], "t")

    assert llm.calls[0].context.call_key != llm.calls[1].context.call_key
