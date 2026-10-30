from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from motionile.engine.ai.graphs.deps import PipelineDependencies
from motionile.engine.ai.graphs.errors import PipelineErrorCode, pipeline_error
from motionile.engine.ai.graphs.events import EventType, FallbackReason, emit
from motionile.engine.ai.graphs.issues import module_issues
from motionile.engine.ai.graphs.stages import Stage
from motionile.engine.ai.graphs.state import PipelineState
from motionile.engine.ai.llm.models import LlmCall, LlmTask
from motionile.engine.ai.nodes.blocks import (
    SceneBrief,
    issues_block,
    module_block,
    module_text,
    narration_block,
    narration_scene_of,
    scene_brief,
    scene_context,
)
from motionile.engine.ai.nodes.calls import REPAIR_KEY, SCENE_KEY, code_system_blocks, load_selected, scene_metadata
from motionile.engine.ai.nodes.common import call_context
from motionile.engine.ai.ports import CompositionIssue, JobSnapshot, LoadedSkill, SceneAttemptKind, SelectedSkills
from motionile.engine.ai.prompts.canary import OutputScanner
from motionile.engine.ai.scenes.fallback import fallback_module
from motionile.engine.ai.scenes.literals import scene_literals
from motionile.engine.ai.scenes.models import SceneModule
from motionile.engine.ai.storyboard import Storyboard, StoryboardScene
from motionile.engine.audio.narration_models import NarrationDocument, NarrationScene

SCANNED_SOURCE = "scene_module"
IMMEDIATE_REASK_ATTEMPT = 1


@dataclass(frozen=True, slots=True)
class SceneWork:
    deps: PipelineDependencies
    job: JobSnapshot
    storyboard: Storyboard
    narration: NarrationDocument
    skills: SelectedSkills
    scanner: OutputScanner

    def scene(self, scene_id: str) -> StoryboardScene:
        return next(scene for scene in self.storyboard.scenes if scene.id == scene_id)

    def narration_scene(self, scene_id: str) -> NarrationScene:
        return narration_scene_of(self.narration, scene_id)

    def brief(self, scene: StoryboardScene) -> SceneBrief:
        return scene_brief(self.storyboard, self.narration, scene)

    def skills_for(self, scene: StoryboardScene) -> list[LoadedSkill]:
        named = [skill for skill in self.skills.visual if skill.summary.slug in scene.visual_skills]
        return [self.skills.style, *self.skills.domain, *(named or self.skills.visual)]


async def load_scene_work(deps: PipelineDependencies, state: PipelineState, job_id: UUID) -> SceneWork:
    job = await deps.store.snapshot(job_id)
    approved = await deps.store.approved_storyboard(job_id)
    narration = await deps.store.narration(job_id)
    if approved is None or narration is None:
        raise pipeline_error(PipelineErrorCode.COMPOSITION_INVALID)
    skills = await load_selected(deps, state)
    scanner = deps.scanner_factory(await deps.prompts.all_active(), ())
    return SceneWork(deps, job, approved.content, narration, skills, scanner)


async def ask_module(  # noqa: PLR0913
    work: SceneWork,
    scene: StoryboardScene,
    *,
    stage: Stage,
    task: LlmTask,
    key: str,
    attempt: int | None = None,
    previous: SceneModule | None = None,
    issues: Sequence[CompositionIssue] = (),
) -> SceneModule:
    blocks = [scene_context(work.brief(scene), attempt), narration_block(work.narration_scene(scene.id))]
    if previous is not None:
        blocks.extend([module_block(previous), issues_block(issues)])
    call = LlmCall(
        task=task,
        context=call_context(work.job, stage, key),
        system_blocks=await code_system_blocks(
            work.deps, SCENE_KEY if task is LlmTask.SCENE else REPAIR_KEY, work.skills_for(scene)
        ),
        user_blocks=blocks,
        metadata=scene_metadata(scene.id),
    )
    produced = (await work.deps.llm.generate(call, SceneModule)).output
    module = produced.model_copy(update={"scene_id": scene.id})
    work.scanner.ensure_clean_scene(module_text(module), scene_literals(module), source=SCANNED_SOURCE)
    return module


async def produce_module(work: SceneWork, scene: StoryboardScene) -> SceneModule:
    module = await ask_module(work, scene, stage=Stage.SCENES, task=LlmTask.SCENE, key=f"scene:{scene.id}")
    findings = module_issues(module)
    if not findings:
        return module
    return await ask_module(
        work,
        scene,
        stage=Stage.SCENES,
        task=LlmTask.REPAIR,
        key=f"scene:{scene.id}:reask",
        attempt=IMMEDIATE_REASK_ATTEMPT,
        previous=module,
        issues=findings,
    )


async def store_fallback(work: SceneWork, scene_id: str, reason: FallbackReason, stage: Stage) -> None:
    await work.deps.store.save_scene_module(work.job.id, fallback_module(scene_id), SceneAttemptKind.FALLBACK, [])
    await emit(work.deps, work.job.id, EventType.SCENE_FALLBACK, stage, {"sceneId": scene_id, "reason": reason.value})
