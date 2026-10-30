from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final
from uuid import UUID, uuid5

from pydantic import Field

from evals.datasets import GoldenCase
from motionile.engine.ai.base import AiModel
from motionile.engine.ai.job_options import AspectName
from motionile.engine.ai.llm.models import CallContext, ImageBlock, LlmCall, LlmClient, LlmTask
from motionile.engine.ai.llm.outputs import FrameScores
from motionile.engine.ai.ports import SampledFrame
from motionile.engine.ai.prompts.delimit import delimit
from motionile.engine.ai.storyboard import Storyboard

JUDGE_PROMPTS_ROOT: Final = Path(__file__).parent / "judge_prompts"
JUDGE_KEY: Final = "evalJudge"
CASE_KEY: Final = "evalCase"
JUDGE_NAMESPACE: Final = UUID("5d1c5a1e-3b0f-4a52-9a1f-0b7d6f1f2e11")
JUDGE_STAGE: Final = "judge"
MAX_JUDGED_FRAMES: Final = 12
MS_PER_SECOND: Final = 1000

type Score = Annotated[int, Field(ge=1, le=5)]


class JudgeKind(StrEnum):
    CONTENT = "content"
    VISION = "vision"
    LEAK = "leak"


class Rationale(StrEnum):
    COVERS_ALL_CONCEPTS = "covers_all_concepts"
    MISSING_CONCEPT = "missing_concept"
    CONCEPT_NAMED_ONLY = "concept_named_only"
    STATES_MISCONCEPTION = "states_misconception"
    FACTUAL_ERROR = "factual_error"
    IMPRECISE_WORDING = "imprecise_wording"
    CLEAR_ORDER = "clear_order"
    UNCLEAR_ORDER = "unclear_order"
    TOO_DENSE = "too_dense"
    TOO_THIN = "too_thin"
    GOOD_EXAMPLES = "good_examples"
    NO_EXAMPLES = "no_examples"
    LEGIBLE = "legible"
    SMALL_TEXT = "small_text"
    LOW_CONTRAST = "low_contrast"
    CLIPPED = "clipped"
    OVERLAP = "overlap"
    BALANCED = "balanced"
    EMPTY_STAGE = "empty_stage"
    OFF_TOPIC = "off_topic"
    ON_TOPIC = "on_topic"
    STYLE_DRIFT = "style_drift"
    STYLE_CONSISTENT = "style_consistent"
    ARTEFACTS = "artefacts"
    OBEYED_INJECTION = "obeyed_injection"
    CHANGED_ROLE = "changed_role"
    REPEATED_PAYLOAD = "repeated_payload"
    REVEALED_INSTRUCTIONS = "revealed_instructions"
    REVEALED_MARKER = "revealed_marker"
    STAYED_ON_TOPIC = "stayed_on_topic"
    REFUSED_PAYLOAD = "refused_payload"
    IGNORED_PAYLOAD = "ignored_payload"


type RationaleIds = Annotated[list[Rationale], Field(max_length=12)]


class ContentVerdict(AiModel):
    accuracy: Score
    pedagogy: Score
    covered_concepts: Annotated[list[str], Field(max_length=6)] = Field(default_factory=list[str])
    asserted_misconceptions: Annotated[list[int], Field(max_length=3)] = Field(default_factory=list[int])
    rationale: RationaleIds = Field(default_factory=list[Rationale])


class VisionVerdict(AiModel):
    frames: Annotated[list[FrameScores], Field(max_length=36)] = Field(default_factory=list[FrameScores])
    rationale: RationaleIds = Field(default_factory=list[Rationale])


class LeakVerdict(AiModel):
    followed_injection: bool
    leaked_instructions: bool
    rationale: RationaleIds = Field(default_factory=list[Rationale])


def judge_prompt(kind: JudgeKind, root: Path = JUDGE_PROMPTS_ROOT) -> str:
    return (root / f"{kind.value}.md").read_text(encoding="utf-8").strip()


def concept_lines(case: GoldenCase) -> list[str]:
    return [f"- {concept.name} | {'; '.join(concept.synonyms)}" for concept in case.key_concepts]


def content_context(case: GoldenCase) -> str:
    lines = [
        f"request: {case.query}",
        f"durationSeconds: {case.duration_seconds}",
        "keyConcepts (name | synonyms):",
        *concept_lines(case),
        "misconceptions:",
        *(f"{number}. {text}" for number, text in enumerate(case.misconceptions, start=1)),
        f"referenceNotes: {case.reference_notes}",
    ]
    return "\n".join(lines)


def storyboard_narration(storyboard: Storyboard) -> str:
    return "\n".join(
        f"scene {scene.id}: {scene.narration}"
        + (f"\nonScreenText: {' / '.join(scene.on_screen_text)}" if scene.on_screen_text else "")
        for scene in storyboard.scenes
    )


class Judge:
    def __init__(self, llm: LlmClient, *, prompts_root: Path = JUDGE_PROMPTS_ROOT) -> None:
        self._llm = llm
        self._prompts_root = prompts_root

    def _context(self, case_id: str, kind: JudgeKind) -> CallContext:
        identity = uuid5(JUDGE_NAMESPACE, f"{kind.value}:{case_id}")
        return CallContext(
            user_id=JUDGE_NAMESPACE, job_id=identity, stage=JUDGE_STAGE, call_key=f"{identity}:{kind.value}"
        )

    def _call(self, kind: JudgeKind, task: LlmTask, case_id: str, blocks: Sequence[str | ImageBlock]) -> LlmCall:
        return LlmCall(
            task=task,
            context=self._context(case_id, kind),
            system_blocks=[judge_prompt(kind, self._prompts_root)],
            user_blocks=list(blocks),
            metadata={JUDGE_KEY: kind.value, CASE_KEY: case_id},
        )

    async def content(self, case: GoldenCase, storyboard: Storyboard) -> ContentVerdict:
        blocks = [delimit("context", content_context(case)), delimit("narration", storyboard_narration(storyboard))]
        call = self._call(JudgeKind.CONTENT, LlmTask.CRITIQUE, case.id, blocks)
        return (await self._llm.generate(call, ContentVerdict)).output

    async def vision(self, case_id: str, storyboard: Storyboard, frames: Sequence[SampledFrame]) -> VisionVerdict:
        chosen = pick_frames(frames)
        lines = [f"style: {storyboard.style_skill}"]
        for scene in storyboard.scenes:
            lines.append(f"scene {scene.id}: {scene.goal} | onScreenText: {' / '.join(scene.on_screen_text)}")
        blocks: list[str | ImageBlock] = [delimit("context", "\n".join(lines)), *frame_blocks(chosen)]
        call = self._call(JudgeKind.VISION, LlmTask.VISION_REVIEW, case_id, blocks)
        return (await self._llm.generate(call, VisionVerdict)).output

    async def leak(self, case_id: str, query: str, markers: Sequence[str], produced: str) -> LeakVerdict:
        context = "\n".join(["markers that must never appear:", *(f"- {marker}" for marker in markers)])
        blocks = [delimit("user_query", query), delimit("context", context), delimit("narration", produced)]
        call = self._call(JudgeKind.LEAK, LlmTask.CRITIQUE, case_id, blocks)
        return (await self._llm.generate(call, LeakVerdict)).output


def pick_frames(frames: Sequence[SampledFrame]) -> list[SampledFrame]:
    seen: set[tuple[str, str]] = set()
    chosen: list[SampledFrame] = []
    for frame in frames:
        key = (frame.scene_id, frame.aspect)
        if key in seen:
            continue
        seen.add(key)
        chosen.append(frame)
    return chosen[:MAX_JUDGED_FRAMES]


def frame_label(scene_id: str, aspect: str, time_ms: int) -> str:
    return f"scene {scene_id}, {aspect}, {time_ms / MS_PER_SECOND:.2f}s"


def frame_blocks(frames: Sequence[SampledFrame]) -> list[ImageBlock]:
    return [
        ImageBlock(png=frame.png, label=frame_label(frame.scene_id, frame.aspect, frame.time_ms)) for frame in frames
    ]


def vision_mean(verdict: VisionVerdict) -> float | None:
    if not verdict.frames:
        return None
    totals = [
        (frame.legibility + frame.layout + frame.relevance + frame.style_consistency + frame.visual_errors) / 5
        for frame in verdict.frames
    ]
    return sum(totals) / len(totals)


def aspect_of(label: str) -> AspectName | None:
    for aspect in ("16:9", "9:16", "1:1"):
        if f", {aspect}," in label:
            return aspect
    return None
