from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import partial

from pydantic import JsonValue

from motionile.engine.ai.graphs.deps import MS_PER_SECOND, PipelineDependencies
from motionile.engine.ai.graphs.events import EventType, emit
from motionile.engine.ai.graphs.issues import to_record
from motionile.engine.ai.graphs.stages import Stage
from motionile.engine.ai.graphs.state import PipelineState
from motionile.engine.ai.llm.models import ImageBlock, LlmCall, LlmError, LlmTask
from motionile.engine.ai.llm.outputs import VisionReview
from motionile.engine.ai.nodes.blocks import narration_block, narration_scene_of, review_context, scene_brief
from motionile.engine.ai.nodes.calls import REVIEW_KEY, system_blocks
from motionile.engine.ai.nodes.common import call_context, job_id_of, run_bounded, stage_scope
from motionile.engine.ai.nodes.composition import Composition, load_composition
from motionile.engine.ai.ports import CompositionIssue, JobSnapshot, SampledFrame
from motionile.engine.ai.review import review_issues
from motionile.engine.ai.storyboard import StoryboardScene
from motionile.engine.render.models import RenderEngineError

SAMPLING_FAILED = "sampling_failed"


@dataclass(frozen=True, slots=True)
class SceneReview:
    scene_id: str
    issues: list[CompositionIssue] = field(default_factory=list[CompositionIssue])
    failure: str | None = None

    @property
    def blocked(self) -> bool:
        return any(issue.is_blocking for issue in self.issues)


def frame_blocks(frames: Sequence[SampledFrame]) -> list[ImageBlock]:
    return [
        ImageBlock(png=frame.png, label=f"scene {frame.scene_id}, {frame.aspect}, {frame.time_ms / MS_PER_SECOND:.2f}s")
        for frame in frames
    ]


async def review_scene(
    deps: PipelineDependencies,
    job: JobSnapshot,
    composition: Composition,
    scene: StoryboardScene,
    frames: Sequence[SampledFrame],
) -> SceneReview:
    attempts = next(record.attempts for record in composition.records if record.scene_id == scene.id)
    brief = scene_brief(composition.storyboard, composition.narration, scene)
    narration = narration_scene_of(composition.narration, scene.id)
    call = LlmCall(
        task=LlmTask.VISION_REVIEW,
        context=call_context(job, Stage.VISUAL_REVIEW, f"review:{scene.id}:{attempts}"),
        system_blocks=await system_blocks(deps, REVIEW_KEY),
        user_blocks=[review_context(brief), narration_block(narration), *frame_blocks(frames)],
    )
    try:
        review = (await deps.llm.generate(call, VisionReview)).output
    except LlmError as error:
        return SceneReview(scene.id, failure=error.code.value)
    return SceneReview(scene.id, review_issues(review, scene_id=scene.id))


def review_report(reviews: Sequence[SceneReview]) -> dict[str, JsonValue]:
    return {
        "issues": [
            {
                "code": issue.code,
                "severity": issue.severity,
                "sceneId": issue.scene_id,
                "aspect": issue.aspect,
                "message": issue.message,
            }
            for review in reviews
            for issue in review.issues
        ],
        "skipped": [{"sceneId": review.scene_id, "code": review.failure} for review in reviews if review.failure],
    }


async def sample(deps: PipelineDependencies, composition: Composition) -> list[SampledFrame] | None:
    try:
        return await deps.checker.sample_frames(composition.html, composition.narration, composition.storyboard.aspects)
    except RenderEngineError:
        return None


async def review_pending(
    deps: PipelineDependencies, job: JobSnapshot, composition: Composition, pending: list[StoryboardScene]
) -> list[SceneReview]:
    frames = await sample(deps, composition)
    if frames is None:
        return [SceneReview(scene.id, failure=SAMPLING_FAILED) for scene in pending]
    jobs = [
        partial(review_scene, deps, job, composition, scene, [frame for frame in frames if frame.scene_id == scene.id])
        for scene in pending
        if any(frame.scene_id == scene.id for frame in frames)
    ]
    return await run_bounded(deps.config.scene_concurrency, jobs)


async def run_visual_review(deps: PipelineDependencies, state: PipelineState) -> PipelineState:
    if not deps.config.visual_review_enabled or state.get("issues"):
        return {}
    job_id = job_id_of(state)
    async with stage_scope(deps, job_id, Stage.VISUAL_REVIEW):
        composition = await load_composition(deps, job_id)
        done = set(state.get("reviewed", []))
        pending = [
            scene
            for scene in composition.storyboard.scenes
            if scene.id not in done and scene.id not in composition.fallback_ids
        ]
        reviews = await review_pending(deps, await deps.store.snapshot(job_id), composition, pending) if pending else []
        issues = [issue for review in reviews for issue in review.issues]
        await deps.store.save_reports(job_id, validation={}, review=review_report(reviews))
        await emit(deps, job_id, EventType.REVIEW_COMPLETED, Stage.VISUAL_REVIEW, {"issues": len(issues)})
        blocked = {review.scene_id for review in reviews if review.blocked}
        return {
            "issues": [to_record(issue, issue.scene_id) for issue in issues if issue.is_blocking and issue.scene_id],
            "reviewed": sorted(({scene.id for scene in pending} - blocked) | done),
        }
