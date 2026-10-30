from collections.abc import Sequence
from functools import cache
from uuid import uuid4

from motionile.engine.ai.job_options import JobOptions, JobStatus
from motionile.engine.ai.llm.outputs import SkillChoice, SkillSelection
from motionile.engine.ai.ports import JobSnapshot, PreferenceContext, SkillLayer, TopicContext
from motionile.engine.ai.skills.examples import SkillExample, extract_examples
from motionile.engine.ai.skills.loader import LIBRARY_ROOT, SkillDocument, load_library


@cache
def library() -> tuple[SkillDocument, ...]:
    return load_library()


@cache
def all_examples() -> tuple[SkillExample, ...]:
    return tuple(example for document in library() for example in extract_examples(document))


def documents_in(layer: SkillLayer) -> tuple[SkillDocument, ...]:
    return tuple(document for document in library() if document.layer is layer)


def example_id(example: SkillExample) -> str:
    return f"{example.skill}:{example.title}"


def skill_text(layer: SkillLayer, slug: str) -> str:
    return (LIBRARY_ROOT / layer.value / slug / "SKILL.md").read_text(encoding="utf-8")


def job(
    query: str = "How does a hash map handle collisions?",
    *,
    style: str = "minimal-dark",
    hints: Sequence[str] = (),
    topic: bool = True,
) -> JobSnapshot:
    return JobSnapshot(
        id=uuid4(),
        user_id=uuid4(),
        source="query",
        query=query,
        topic=TopicContext(
            id=uuid4(),
            title="Hash maps",
            description="Buckets, hashing and collisions.",
            category="Computer science",
            subcategory="Data structures",
            skill_hints=tuple(hints),
        )
        if topic
        else None,
        options=JobOptions(
            duration_seconds=60,
            aspects=["16:9", "9:16"],
            style=style,
            voice_id=uuid4(),
            language="en",
        ),
        status=JobStatus.PLANNING,
        cancel_requested=False,
        preferences=PreferenceContext(depth="beginner"),
    )


def choice(slug: str, reason: str = "It helps.") -> SkillChoice:
    return SkillChoice(slug=slug, reason=reason)


def selection(style: str, visual: Sequence[str] = (), domain: Sequence[str] = ()) -> SkillSelection:
    return SkillSelection(
        style=choice(style),
        visual=[choice(slug) for slug in visual],
        domain=[choice(slug) for slug in domain],
    )
