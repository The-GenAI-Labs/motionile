from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel

from evals.browser import SandboxChecker
from evals.context import SuiteContext
from evals.datasets import GoldenCase
from evals.errors import EvalError
from evals.harness import ObservingChecker, RigParts, build_rig, make_job
from evals.judge import VisionVerdict, vision_mean
from evals.skill_library import LibrarySkillCatalog
from motionile.engine.ai.graphs.run import RunOutcome
from motionile.engine.ai.llm.models import LlmCall, LlmClient, LlmResult, LlmTask
from motionile.engine.ai.ports import CompositionIssue, SampledFrame
from motionile.engine.ai.scenes.models import SceneModule
from motionile.engine.ai.scenes.static_checks import check_scene_module
from motionile.engine.ai.storyboard import Storyboard
from motionile.engine.audio.narration_models import NarrationDocument

if TYPE_CHECKING:
    from motionile.engine.render.sandbox import RenderSandbox

NAMESPACE: Final = "scenes"
MEMO_PREFIX: Final = "scene-run:"


class GraphDidNotFinishError(EvalError):
    code = "eval_graph_failed"


@dataclass(slots=True)
class StaticTally:
    passed: int = 0
    total: int = 0


class ObservingLlm:
    def __init__(self, inner: LlmClient, tally: StaticTally) -> None:
        self._inner = inner
        self._tally = tally

    async def generate[OutputT: BaseModel](self, call: LlmCall, output: type[OutputT]) -> LlmResult[OutputT]:
        if call.task is not LlmTask.SCENE:
            return await self._inner.generate(call, output)
        self._tally.total += 1
        result = await self._inner.generate(call, output)
        if isinstance(result.output, SceneModule) and not check_scene_module(result.output):
            self._tally.passed += 1
        return result


@dataclass(frozen=True, slots=True)
class SceneRunArtifacts:
    case_id: str
    storyboard: Storyboard
    narration: NarrationDocument
    html: str
    aspects: tuple[str, ...]
    scene_ids: tuple[str, ...]
    clean_first_pass: int
    static_passed: int
    static_total: int
    fallback_scenes: int
    repair_attempts: int
    frames: tuple[SampledFrame, ...] = field(default=(), repr=False)
    vision: VisionVerdict | None = None

    @property
    def scene_count(self) -> int:
        return len(self.scene_ids)

    @property
    def vision_score(self) -> float | None:
        return vision_mean(self.vision) if self.vision is not None else None


def scenes_clean_on_first_pass(scene_ids: list[str], issues: tuple[CompositionIssue, ...]) -> int:
    blocking = [issue for issue in issues if issue.is_blocking]
    if any(issue.scene_id is None for issue in blocking):
        return 0
    failing = {issue.scene_id for issue in blocking}
    return sum(1 for scene_id in scene_ids if scene_id not in failing)


async def run_scene_case(context: SuiteContext, sandbox: "RenderSandbox", case: GoldenCase) -> SceneRunArtifacts:
    key = f"{MEMO_PREFIX}{case.id}"
    cached = context.memo.get(key)
    if isinstance(cached, SceneRunArtifacts):
        return cached
    async with context.sessions.open(NAMESPACE, case.id) as session:
        tally = StaticTally()
        checker = ObservingChecker(SandboxChecker(sandbox))
        parts = RigParts(
            llm=ObservingLlm(session.llm, tally),
            prompts=context.prompts,
            checker=checker,
            embedder=session.embedder,
            limits=context.limits,
        )
        job = make_job(
            query=case.query, duration_seconds=case.duration_seconds, aspects=case.aspects, language=case.language
        )
        rig = await build_rig(job, parts, LibrarySkillCatalog(session.embedder))
        outcome = await rig.run()
        if outcome is not RunOutcome.FINISHED or rig.store.narration_document is None or not rig.store.storyboards:
            code = rig.store.failure[0] if rig.store.failure else outcome.value
            raise GraphDidNotFinishError(code)
        storyboard = (await rig.store.approved_storyboard(job.id) or rig.store.storyboards[-1]).content
        scene_ids = [scene.id for scene in storyboard.scenes]
        first = checker.first_check
        vision: VisionVerdict | None = None
        if session.judge is not None and checker.last_frames:
            vision = await session.judge.vision(case.id, storyboard, checker.last_frames)
        records = list(rig.store.records.values())
        artifacts = SceneRunArtifacts(
            case_id=case.id,
            storyboard=storyboard,
            narration=rig.store.narration_document,
            html=checker.last_html,
            aspects=tuple(case.aspects),
            scene_ids=tuple(scene_ids),
            clean_first_pass=scenes_clean_on_first_pass(scene_ids, first.issues) if first is not None else 0,
            static_passed=tally.passed,
            static_total=tally.total,
            fallback_scenes=sum(1 for record in records if record.is_fallback),
            repair_attempts=sum(record.attempts for record in records),
            frames=tuple(checker.last_frames),
            vision=vision,
        )
    context.memo[key] = artifacts
    return artifacts
