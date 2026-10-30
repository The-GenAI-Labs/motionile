from collections.abc import Mapping, Sequence
from typing import Final

from motionile.engine.ai.graphs.deps import PipelineDependencies
from motionile.engine.ai.graphs.errors import PipelineErrorCode, pipeline_error
from motionile.engine.ai.graphs.state import PipelineState
from motionile.engine.ai.job_options import JobOptions
from motionile.engine.ai.llm.metadata import CallMetadataKey, join_aspects
from motionile.engine.ai.ports import JobSnapshot, LoadedSkill, SelectedSkills, SkillLayer
from motionile.engine.ai.prompts.loader import load_runtime_reference
from motionile.engine.ai.prompts.render import render_active

PLANNER_KEY: Final = "planner.storyboard"
CRITIC_KEY: Final = "critic.storyboard"
SCENE_KEY: Final = "scene.module"
REPAIR_KEY: Final = "repair.scene"
REVIEW_KEY: Final = "review.vision"
RUNTIME_REFERENCE_VARIABLE: Final = "runtime_reference"
MAX_TOPIC_METADATA_CHARS: Final = 200


def skill_block(skill: LoadedSkill) -> str:
    return f"# Skill: {skill.summary.name}\n\n{skill.body}"


async def system_blocks(
    deps: PipelineDependencies, key: str, skills: Sequence[LoadedSkill] = (), variables: Mapping[str, str] | None = None
) -> list[str]:
    prompt = await deps.prompts.active(key)
    return [render_active(prompt, variables), *(skill_block(skill) for skill in skills)]


async def code_system_blocks(deps: PipelineDependencies, key: str, skills: Sequence[LoadedSkill]) -> list[str]:
    return await system_blocks(deps, key, skills, {RUNTIME_REFERENCE_VARIABLE: load_runtime_reference()})


async def load_selected(deps: PipelineDependencies, state: PipelineState) -> SelectedSkills:
    loaded = await deps.catalog.load(state.get("skills", []))
    by_layer = {layer: tuple(skill for skill in loaded if skill.summary.layer is layer) for layer in SkillLayer}
    if not by_layer[SkillLayer.STYLE]:
        raise pipeline_error(PipelineErrorCode.NO_STYLE_SKILL)
    return SelectedSkills(
        style=by_layer[SkillLayer.STYLE][0],
        visual=by_layer[SkillLayer.VISUAL],
        domain=by_layer[SkillLayer.DOMAIN],
        reasons={},
    )


def plan_metadata(job: JobSnapshot) -> dict[str, str]:
    options: JobOptions = job.options
    topic = job.topic.title if job.topic is not None else job.query[:MAX_TOPIC_METADATA_CHARS]
    metadata = {
        CallMetadataKey.DURATION_MS.value: str(options.target_duration_ms),
        CallMetadataKey.ASPECTS.value: join_aspects(list(options.aspects)),
        CallMetadataKey.LANGUAGE.value: options.language,
        CallMetadataKey.STYLE.value: options.style,
    }
    if topic:
        metadata[CallMetadataKey.TOPIC.value] = topic
    return metadata


def scene_metadata(scene_id: str) -> dict[str, str]:
    return {CallMetadataKey.SCENE_ID.value: scene_id}
