from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

import structlog

from motionile.engine.ai.llm.models import (
    CallContext,
    Embedder,
    LlmCall,
    LlmClient,
    LlmTask,
    ModelOutputInvalidError,
)
from motionile.engine.ai.llm.outputs import SkillChoice, SkillSelection
from motionile.engine.ai.ports import (
    JobSnapshot,
    LoadedSkill,
    PromptStore,
    SelectedSkills,
    SkillCatalog,
    SkillLayer,
    SkillSummary,
)
from motionile.engine.ai.prompts import delimit, render_active
from motionile.engine.ai.skills.errors import NoStyleSkillError

ROUTER_PROMPT_KEY: Final = "router.skills"
NEAREST_PER_LAYER: Final = 8
MAX_VISUAL: Final = 3
MAX_DOMAIN: Final = 2
FALLBACK_VISUAL: Final = 2
FALLBACK_DOMAIN: Final = 1
MAX_REASON_LENGTH: Final = 160
MAX_DESCRIPTION_LENGTH: Final = 400
MAX_EMBEDDING_TEXT: Final = 6_000
LAYER_LIMITS: Final[Mapping[SkillLayer, int]] = MappingProxyType(
    {SkillLayer.STYLE: 1, SkillLayer.VISUAL: MAX_VISUAL, SkillLayer.DOMAIN: MAX_DOMAIN}
)
LAYER_TITLES: Final[Mapping[SkillLayer, str]] = MappingProxyType(
    {SkillLayer.STYLE: "Style", SkillLayer.VISUAL: "Visual", SkillLayer.DOMAIN: "Domain"}
)
REQUESTED_STYLE_REASON: Final = "The style requested for this video."
SIMILARITY_REASON: Final = "Closest match to the request by similarity."
HINT_REASON: Final = "Suggested by the topic catalog."
NO_REASON: Final = "Chosen for this video."

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CandidatePool:
    by_layer: Mapping[SkillLayer, tuple[SkillSummary, ...]]
    hinted: frozenset[str]

    def slugs(self, layer: SkillLayer) -> frozenset[str]:
        return frozenset(summary.slug for summary in self.by_layer[layer])

    def ranked(self, layer: SkillLayer) -> tuple[SkillSummary, ...]:
        return tuple(sorted(self.by_layer[layer], key=self._rank))

    def _rank(self, summary: SkillSummary) -> tuple[int, float, str]:
        similarity = summary.similarity if summary.similarity is not None else -1.0
        return (0 if summary.slug in self.hinted else 1, -similarity, summary.slug)


@dataclass(frozen=True, slots=True)
class Picks:
    style: str
    visual: tuple[str, ...]
    domain: tuple[str, ...]
    reasons: Mapping[str, str]

    @property
    def slugs(self) -> tuple[str, ...]:
        return (self.style, *self.visual, *self.domain)


def embedding_text(job: JobSnapshot) -> str:
    parts = [job.query]
    if job.topic is not None:
        parts.extend([job.topic.title, job.topic.description or ""])
    return "\n".join(part for part in parts if part)[:MAX_EMBEDDING_TEXT]


def truncated(text: str, limit: int) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def candidate_line(summary: SkillSummary, hinted: frozenset[str]) -> str:
    similarity = f"{summary.similarity:.2f}" if summary.similarity is not None else "n/a"
    hint = " | topic hint" if summary.slug in hinted else ""
    return (
        f"- {summary.slug} | {summary.name} | cost {summary.token_count} tokens | similarity {similarity}{hint} | "
        f"{truncated(summary.description, MAX_DESCRIPTION_LENGTH)}"
    )


def context_text(job: JobSnapshot, pool: CandidatePool, token_budget: int) -> str:
    options = job.options
    lines = ["Job"]
    if job.topic is not None:
        lines.append(f"- Topic: {job.topic.title} ({job.topic.category} / {job.topic.subcategory})")
        if job.topic.description:
            lines.append(f"- Topic summary: {truncated(job.topic.description, MAX_DESCRIPTION_LENGTH)}")
    lines.extend(
        [
            f"- Language: {options.language}",
            f"- Duration: {options.duration_seconds} seconds",
            f"- Aspects: {', '.join(options.aspects)}",
        ]
    )
    if job.preferences.depth:
        lines.append(f"- Depth preference: {job.preferences.depth}")
    topic_hints = ", ".join(sorted(pool.hinted)) or "none"
    lines.extend(
        [
            "",
            f"Style requested by the user: {options.style}",
            f"Limits: exactly 1 style, at most {MAX_VISUAL} visual, at most {MAX_DOMAIN} domain",
            f"Token budget: {token_budget} tokens in total for everything you choose, the style included",
            f"Topic skill hints: {topic_hints}",
        ]
    )
    for layer in SkillLayer:
        lines.extend(["", f"Candidates, {LAYER_TITLES[layer]} layer"])
        lines.extend(candidate_line(summary, pool.hinted) for summary in pool.by_layer[layer])
    return "\n".join(lines)


def clean_reason(choice: SkillChoice) -> str:
    return truncated(choice.reason, MAX_REASON_LENGTH)


def kept_choices(choices: Sequence[SkillChoice], allowed: frozenset[str], limit: int) -> list[SkillChoice]:
    seen: set[str] = set()
    kept: list[SkillChoice] = []
    for choice in choices:
        if choice.slug in allowed and choice.slug not in seen:
            seen.add(choice.slug)
            kept.append(choice)
    return kept[:limit]


def model_picks(selection: SkillSelection, pool: CandidatePool, requested_style: str) -> Picks:
    visual = kept_choices(selection.visual, pool.slugs(SkillLayer.VISUAL), MAX_VISUAL)
    domain = kept_choices(selection.domain, pool.slugs(SkillLayer.DOMAIN), MAX_DOMAIN)
    reasons = {choice.slug: clean_reason(choice) for choice in (*visual, *domain)}
    style_reason = clean_reason(selection.style) if selection.style.slug == requested_style else None
    reasons[requested_style] = style_reason or REQUESTED_STYLE_REASON
    return Picks(
        style=requested_style,
        visual=tuple(choice.slug for choice in visual),
        domain=tuple(choice.slug for choice in domain),
        reasons=reasons,
    )


def fallback_picks(pool: CandidatePool, requested_style: str) -> Picks:
    visual = pool.ranked(SkillLayer.VISUAL)[:FALLBACK_VISUAL]
    domain = pool.ranked(SkillLayer.DOMAIN)[:FALLBACK_DOMAIN]
    reasons = {summary.slug: reason_for_fallback(summary, pool) for summary in (*visual, *domain)}
    reasons[requested_style] = REQUESTED_STYLE_REASON
    return Picks(
        style=requested_style,
        visual=tuple(summary.slug for summary in visual),
        domain=tuple(summary.slug for summary in domain),
        reasons=reasons,
    )


def reason_for_fallback(summary: SkillSummary, pool: CandidatePool) -> str:
    return HINT_REASON if summary.slug in pool.hinted else SIMILARITY_REASON


def within_budget(
    style: LoadedSkill, visual: Sequence[LoadedSkill], domain: Sequence[LoadedSkill], token_budget: int
) -> tuple[list[LoadedSkill], list[LoadedSkill]]:
    kept_visual = list(visual)
    kept_domain = list(domain)

    def total() -> int:
        return style.token_count + sum(skill.token_count for skill in (*kept_visual, *kept_domain))

    while total() > token_budget and (kept_domain or kept_visual):
        if kept_domain:
            kept_domain.pop()
        else:
            kept_visual.pop()
    return kept_visual, kept_domain


class LibrarySkillRouter:
    def __init__(self, catalog: SkillCatalog, embedder: Embedder, llm: LlmClient, prompts: PromptStore) -> None:
        self._catalog = catalog
        self._embedder = embedder
        self._llm = llm
        self._prompts = prompts

    async def select(self, job: JobSnapshot, context: CallContext, *, token_budget: int) -> SelectedSkills:
        pool = await self._candidates(job, context)
        requested_style = job.options.style
        if requested_style not in pool.slugs(SkillLayer.STYLE):
            raise NoStyleSkillError(requested_style)
        picks = await self._picks(job, context, pool, token_budget)
        return await self._assemble(picks, token_budget)

    async def _candidates(self, job: JobSnapshot, context: CallContext) -> CandidatePool:
        (embedding,) = await self._embedder.embed([embedding_text(job)], context)
        hints = job.topic.skill_hints if job.topic is not None else ()
        by_layer: dict[SkillLayer, dict[str, SkillSummary]] = {}
        for layer in SkillLayer:
            nearest = await self._catalog.nearest(layer, embedding, NEAREST_PER_LAYER)
            by_layer[layer] = {summary.slug: summary for summary in nearest if summary.layer is layer}
        hinted: set[str] = set()
        for summary in await self._catalog.by_slugs([*dict.fromkeys([*hints, job.options.style])]):
            by_layer[summary.layer].setdefault(summary.slug, summary)
            if summary.slug in hints:
                hinted.add(summary.slug)
        return CandidatePool(
            by_layer={layer: tuple(candidates.values()) for layer, candidates in by_layer.items()},
            hinted=frozenset(hinted),
        )

    async def _picks(self, job: JobSnapshot, context: CallContext, pool: CandidatePool, token_budget: int) -> Picks:
        prompt = await self._prompts.active(ROUTER_PROMPT_KEY)
        call = LlmCall(
            task=LlmTask.ROUTE,
            context=context,
            system_blocks=[render_active(prompt)],
            user_blocks=[
                delimit("context", context_text(job, pool, token_budget)),
                delimit("user_query", job.query),
            ],
        )
        try:
            result = await self._llm.generate(call, SkillSelection)
        except ModelOutputInvalidError:
            logger.warning("skills.router_fallback", job_id=str(context.job_id))
            return fallback_picks(pool, job.options.style)
        return model_picks(result.output, pool, job.options.style)

    async def _assemble(self, picks: Picks, token_budget: int) -> SelectedSkills:
        loaded = {skill.summary.slug: skill for skill in await self._catalog.load(picks.slugs)}
        style = loaded.get(picks.style)
        if style is None:
            raise NoStyleSkillError(picks.style)
        visual = [loaded[slug] for slug in picks.visual if slug in loaded]
        domain = [loaded[slug] for slug in picks.domain if slug in loaded]
        kept_visual, kept_domain = within_budget(style, visual, domain, token_budget)
        chosen = (style, *kept_visual, *kept_domain)
        return SelectedSkills(
            style=style,
            visual=tuple(kept_visual),
            domain=tuple(kept_domain),
            reasons=MappingProxyType(
                {skill.summary.slug: picks.reasons.get(skill.summary.slug, NO_REASON) for skill in chosen}
            ),
        )
