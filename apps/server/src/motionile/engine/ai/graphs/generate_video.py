from collections.abc import Awaitable, Callable
from typing import Any, Final, Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph  # type: ignore[reportMissingTypeStubs]
from langgraph.graph.state import CompiledStateGraph  # type: ignore[reportMissingTypeStubs]

from motionile.engine.ai.graphs.deps import PipelineDependencies
from motionile.engine.ai.graphs.stages import Stage
from motionile.engine.ai.graphs.state import PipelineState
from motionile.engine.ai.nodes.approval import run_approval, run_decision
from motionile.engine.ai.nodes.composition import run_compose
from motionile.engine.ai.nodes.context import run_context
from motionile.engine.ai.nodes.critique import run_critique
from motionile.engine.ai.nodes.finalize import run_finalize
from motionile.engine.ai.nodes.guard import run_guard
from motionile.engine.ai.nodes.plan import run_plan
from motionile.engine.ai.nodes.render import run_render
from motionile.engine.ai.nodes.repair import run_repair
from motionile.engine.ai.nodes.scenes import run_scenes
from motionile.engine.ai.nodes.validate import run_validate
from motionile.engine.ai.nodes.visual_review import run_visual_review
from motionile.engine.ai.nodes.voice import run_voice

type CompiledGraph = CompiledStateGraph[PipelineState, None, PipelineState, PipelineState]
type NodeFunction = Callable[[PipelineDependencies, PipelineState], Awaitable[PipelineState]]


class BoundNode(Protocol):
    async def __call__(self, state: PipelineState) -> PipelineState: ...


NODES: Final[dict[Stage, NodeFunction]] = {
    Stage.GUARD: run_guard,
    Stage.CONTEXT: run_context,
    Stage.PLAN: run_plan,
    Stage.CRITIQUE: run_critique,
    Stage.APPROVAL: run_approval,
    Stage.DECISION: run_decision,
    Stage.VOICE: run_voice,
    Stage.SCENES: run_scenes,
    Stage.COMPOSE: run_compose,
    Stage.VALIDATE: run_validate,
    Stage.VISUAL_REVIEW: run_visual_review,
    Stage.REPAIR: run_repair,
    Stage.RENDER: run_render,
    Stage.FINALIZE: run_finalize,
}
LINEAR_EDGES: Final[tuple[tuple[Stage, Stage], ...]] = (
    (Stage.GUARD, Stage.CONTEXT),
    (Stage.CONTEXT, Stage.PLAN),
    (Stage.PLAN, Stage.CRITIQUE),
    (Stage.CRITIQUE, Stage.APPROVAL),
    (Stage.VOICE, Stage.SCENES),
    (Stage.COMPOSE, Stage.VALIDATE),
    (Stage.VALIDATE, Stage.VISUAL_REVIEW),
    (Stage.RENDER, Stage.FINALIZE),
)


def bind(deps: PipelineDependencies, node: NodeFunction) -> BoundNode:
    async def run(state: PipelineState) -> PipelineState:
        return await node(deps, state)

    return run


def after_approval(state: PipelineState) -> str:
    return Stage.DECISION.value if state.get("approval_requested") else Stage.VOICE.value


def after_decision(state: PipelineState) -> str:
    return Stage.PLAN.value if state.get("decision") == "regenerate" else Stage.VOICE.value


def after_generation(state: PipelineState) -> str:
    return Stage.REPAIR.value if state.get("issues") else Stage.COMPOSE.value


def after_review(state: PipelineState) -> str:
    return Stage.REPAIR.value if state.get("issues") else Stage.RENDER.value


def build_graph(deps: PipelineDependencies, checkpointer: BaseCheckpointSaver[Any]) -> CompiledGraph:
    graph = StateGraph(PipelineState)
    for stage, node in NODES.items():
        graph.add_node(stage.value, bind(deps, node))  # type: ignore[reportUnknownMemberType]
    graph.add_edge(START, Stage.GUARD.value)
    for source, target in LINEAR_EDGES:
        graph.add_edge(source.value, target.value)
    graph.add_conditional_edges(Stage.APPROVAL.value, after_approval, [Stage.DECISION.value, Stage.VOICE.value])
    graph.add_conditional_edges(Stage.DECISION.value, after_decision, [Stage.PLAN.value, Stage.VOICE.value])
    graph.add_conditional_edges(Stage.SCENES.value, after_generation, [Stage.REPAIR.value, Stage.COMPOSE.value])
    graph.add_conditional_edges(Stage.REPAIR.value, after_generation, [Stage.REPAIR.value, Stage.COMPOSE.value])
    graph.add_conditional_edges(Stage.VISUAL_REVIEW.value, after_review, [Stage.REPAIR.value, Stage.RENDER.value])
    graph.add_edge(Stage.FINALIZE.value, END)
    return graph.compile(checkpointer=checkpointer)  # type: ignore[reportUnknownMemberType]
