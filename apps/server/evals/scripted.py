import re
from dataclasses import replace
from pathlib import Path
from typing import Final

from pydantic import BaseModel

from evals.datasets import AdversarialCase, Datasets, GoldenCase
from evals.judge import (
    CASE_KEY,
    JUDGE_KEY,
    ContentVerdict,
    JudgeKind,
    LeakVerdict,
    Rationale,
    VisionVerdict,
)
from evals.matching import content_tokens, phrase_matches
from evals.scripted_plan import PlanRequest, generic_storyboard, scripted_storyboard
from motionile.engine.ai.guardrails.decision import GuardDecision
from motionile.engine.ai.job_options import AspectName
from motionile.engine.ai.llm.config import StaticBudget
from motionile.engine.ai.llm.fake import FakeLlm
from motionile.engine.ai.llm.metadata import CallMetadataKey, split_aspects
from motionile.engine.ai.llm.models import LlmCall, LlmResult, LlmTask, LlmUsage, UsageLedger
from motionile.engine.ai.llm.outputs import FrameScores, SkillChoice, SkillSelection
from motionile.engine.ai.llm.usage import estimate_blocks_tokens, estimate_tokens, usage_context
from motionile.engine.ai.prompts.delimit import neutralize

JOB_TOKEN_BUDGET: Final = 600_000
FRAME_LABEL: Final = re.compile(r"^scene (?P<scene>[a-z][a-z0-9-]*), (?P<aspect>16:9|9:16|1:1), ")
POSITION: Final = re.compile(r"^position: (?P<position>\d+)$", re.MULTILINE)
STYLE_LINE: Final = re.compile(r"^Style requested by the user: (?P<style>[a-z0-9-]+)$", re.MULTILINE)
CANDIDATE_HEADER: Final = re.compile(r"^Candidates, (?P<layer>Style|Visual|Domain) layer$", re.MULTILINE)
CANDIDATE_LINE: Final = re.compile(r"^- (?P<slug>[a-z0-9-]+) \|", re.MULTILINE)
KIND_TAGS: Final = {
    "query": "user_query",
    "storyboard_edit": "storyboard_edit",
    "instructions": "revision_instructions",
}
SCENE_CYCLE: Final = (
    "kinetic-typography",
    "flow-diagram",
    "code-walkthrough",
    "data-structure",
    "comparison-split",
    "default",
    "responsive-scene",
    "css-animation-scene",
)
OVERFLOW_EVERY: Final = 5
OVERFLOW_AT: Final = 4
SYNTAX_EVERY: Final = 6
SYNTAX_AT: Final = 5
REPAIR_FIXTURE: Final = "kinetic-typography"
JUDGE_CONCEPT_RATIO: Final = 0.6
FULL_COVERAGE: Final = 0.75
PARTIAL_COVERAGE: Final = 0.5
MIN_GOOD_SCENES: Final = 3
GOOD_PEDAGOGY: Final = 4
VISUAL_PICKS: Final = 2
DOMAIN_PICKS: Final = 1


def block_text(call: LlmCall, tag: str) -> str | None:
    opening = f"<{tag}>\n"
    closing = f"\n</{tag}>"
    for block in call.user_blocks:
        if isinstance(block, str) and block.startswith(opening) and block.endswith(closing):
            return block[len(opening) : -len(closing)]
    return None


def candidates_of(context: str, layer: str) -> list[str]:
    headers = list(CANDIDATE_HEADER.finditer(context))
    for index, header in enumerate(headers):
        if header["layer"] != layer:
            continue
        end = headers[index + 1].start() if index + 1 < len(headers) else len(context)
        return [match["slug"] for match in CANDIDATE_LINE.finditer(context[header.end() : end])]
    return []


class ScriptedLlm:
    def __init__(self, *, fixtures_root: Path, ledger: UsageLedger, datasets: Datasets) -> None:
        self._ledger = ledger
        self._fake = FakeLlm(fixtures_root=fixtures_root, ledger=ledger, budget=StaticBudget(JOB_TOKEN_BUDGET))
        self._golden = {case.query: case for case in datasets.golden.cases}
        self._golden_by_id = {case.id: case for case in datasets.golden.cases}
        self._durations = {case.query for case in datasets.duration.cases}
        self._adversarial: dict[tuple[str, str], AdversarialCase] = {
            (KIND_TAGS[case.kind], neutralize(case.text)): case for case in datasets.adversarial.cases
        }

    async def generate[OutputT: BaseModel](self, call: LlmCall, output: type[OutputT]) -> LlmResult[OutputT]:
        judge = call.metadata.get(JUDGE_KEY)
        if judge is not None:
            return await self._answer(call, output, self._judge(call, JudgeKind(judge)))
        if call.task is LlmTask.GUARD:
            return await self._answer(call, output, self._guard(call))
        if call.task is LlmTask.ROUTE:
            return await self._answer(call, output, self._route(call))
        if call.task is LlmTask.PLAN:
            return await self._plan(call, output)
        if call.task in (LlmTask.SCENE, LlmTask.REPAIR):
            return await self._fake.generate(self._with_scene_fixture(call), output)
        return await self._fake.generate(call, output)

    async def _answer[OutputT: BaseModel](
        self, call: LlmCall, output: type[OutputT], answer: BaseModel
    ) -> LlmResult[OutputT]:
        text = answer.model_dump_json(by_alias=True)
        usage = LlmUsage(
            provider="fake",
            model=f"fake/{call.task.value}",
            input_tokens=estimate_blocks_tokens(call.system_blocks, call.user_blocks),
            output_tokens=estimate_tokens(text),
            cached_input_tokens=0,
            cost_micros_usd=0,
        )
        await self._ledger.record(usage_context(call.context, usage.model, 0), call.task, usage)
        return LlmResult(output=output.model_validate_json(text), usage=usage, attempts=1, fallback_used=False)

    async def _plan[OutputT: BaseModel](self, call: LlmCall, output: type[OutputT]) -> LlmResult[OutputT]:
        query = block_text(call, "user_query")
        case = self._golden.get(query) if query is not None else None
        if query is None or (case is None and query not in self._durations):
            return await self._fake.generate(call, output)
        metadata = call.metadata
        aspects: list[AspectName] = [
            aspect for aspect in ("16:9", "9:16", "1:1") if aspect in split_aspects(metadata[CallMetadataKey.ASPECTS])
        ]
        request = PlanRequest(
            duration_ms=int(metadata[CallMetadataKey.DURATION_MS]),
            aspects=aspects,
            language=metadata[CallMetadataKey.LANGUAGE],
            style=metadata[CallMetadataKey.STYLE],
        )
        storyboard = scripted_storyboard(case, request) if case is not None else generic_storyboard(query, request)
        return await self._answer(call, output, storyboard)

    def _guard(self, call: LlmCall) -> GuardDecision:
        for tag in KIND_TAGS.values():
            text = block_text(call, tag)
            if text is None:
                continue
            case = self._adversarial.get((tag, text))
            if case is not None and case.expected == "refuse" and case.expected_code is not None:
                return GuardDecision(verdict="refuse", code=case.expected_code, reason="The request is out of scope.")
        return GuardDecision(verdict="allow", reason="The request asks for an educational explanation.")

    def _route(self, call: LlmCall) -> SkillSelection:
        context = block_text(call, "context") or ""
        style_match = STYLE_LINE.search(context)
        style = style_match["style"] if style_match else "minimal-dark"
        reason = "Closest match to the topic."
        visual = candidates_of(context, "Visual")[:VISUAL_PICKS]
        domain = candidates_of(context, "Domain")[:DOMAIN_PICKS]
        return SkillSelection(
            style=SkillChoice(slug=style, reason="The requested style."),
            visual=[SkillChoice(slug=slug, reason=reason) for slug in visual],
            domain=[SkillChoice(slug=slug, reason=reason) for slug in domain],
        )

    def _with_scene_fixture(self, call: LlmCall) -> LlmCall:
        first = next((block for block in call.user_blocks if isinstance(block, str)), "")
        position_match = POSITION.search(first)
        position = int(position_match["position"]) if position_match else 0
        if call.task is LlmTask.REPAIR:
            name = REPAIR_FIXTURE
        elif position % OVERFLOW_EVERY == OVERFLOW_AT:
            name = "broken-overflow"
        elif position % SYNTAX_EVERY == SYNTAX_AT:
            name = "broken-syntax"
        else:
            name = SCENE_CYCLE[position % len(SCENE_CYCLE)]
        return replace(call, metadata={**call.metadata, CallMetadataKey.FIXTURE.value: name})

    def _judge(self, call: LlmCall, kind: JudgeKind) -> BaseModel:
        if kind is JudgeKind.CONTENT:
            return self._content(call)
        if kind is JudgeKind.VISION:
            return self._vision(call)
        return LeakVerdict(followed_injection=False, leaked_instructions=False, rationale=[Rationale.STAYED_ON_TOPIC])

    def _content(self, call: LlmCall) -> ContentVerdict:
        case: GoldenCase = self._golden_by_id[call.metadata[CASE_KEY]]
        text = block_text(call, "narration") or ""
        tokens = set(content_tokens(text))
        covered = [
            concept.name
            for concept in case.key_concepts
            if any(phrase_matches(phrase, tokens, JUDGE_CONCEPT_RATIO) for phrase in concept.phrases)
        ]
        coverage = len(covered) / len(case.key_concepts)
        scenes = sum(1 for line in text.splitlines() if line.startswith("scene "))
        accuracy = 5 if coverage >= FULL_COVERAGE else 4 if coverage >= PARTIAL_COVERAGE else 3
        pedagogy = 4 if scenes >= MIN_GOOD_SCENES else 3
        rationale = [
            Rationale.COVERS_ALL_CONCEPTS if len(covered) == len(case.key_concepts) else Rationale.MISSING_CONCEPT
        ]
        rationale.append(Rationale.CLEAR_ORDER if pedagogy == GOOD_PEDAGOGY else Rationale.TOO_DENSE)
        return ContentVerdict(
            accuracy=accuracy,
            pedagogy=pedagogy,
            covered_concepts=covered,
            asserted_misconceptions=[],
            rationale=rationale,
        )

    def _vision(self, call: LlmCall) -> VisionVerdict:
        frames: list[FrameScores] = []
        for block in call.user_blocks:
            label = getattr(block, "label", None)
            match = FRAME_LABEL.match(label) if isinstance(label, str) else None
            if match is None:
                continue
            aspect: AspectName = "16:9" if match["aspect"] == "16:9" else "9:16" if match["aspect"] == "9:16" else "1:1"
            frames.append(
                FrameScores(
                    scene_id=match["scene"],
                    aspect=aspect,
                    legibility=5,
                    layout=4,
                    relevance=4,
                    style_consistency=4,
                    visual_errors=5,
                )
            )
        return VisionVerdict(frames=frames, rationale=[Rationale.LEGIBLE, Rationale.ON_TOPIC])
