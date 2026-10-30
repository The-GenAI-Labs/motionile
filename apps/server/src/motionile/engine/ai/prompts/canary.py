import base64
import re
import secrets
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import islice
from typing import Final, Literal

import structlog

from motionile.engine.ai.llm.models import OutputBlockedError
from motionile.engine.ai.ports import ActivePrompt, LoadedSkill

CANARY_PREFIX: Final = "mo-canary-"
CANARY_RANDOM_BYTES: Final = 18
OVERLAP_WORDS: Final = 12
SKILL_OVERLAP_WORDS: Final = 24
CANARY_FRAGMENT_CHARS: Final = 12
WORD = re.compile(r"[^\W_]+")
NON_ALPHANUMERIC = re.compile(r"[\W_]+")

logger = structlog.get_logger(__name__)

type ScanKind = Literal["canary", "overlap"]


def new_canary() -> str:
    return f"{CANARY_PREFIX}{secrets.token_urlsafe(CANARY_RANDOM_BYTES)}"


@dataclass(frozen=True, slots=True)
class ScanResult:
    kind: ScanKind | None = None

    @property
    def blocked(self) -> bool:
        return self.kind is not None


def squash(text: str) -> str:
    return NON_ALPHANUMERIC.sub("", unicodedata.normalize("NFKC", text).casefold())


def words_of(text: str) -> list[str]:
    return WORD.findall(unicodedata.normalize("NFKC", text).casefold())


def shingles_of(words: Sequence[str], size: int = OVERLAP_WORDS) -> Iterable[tuple[str, ...]]:
    if len(words) < size:
        return ()
    return zip(*(islice(words, offset, None) for offset in range(size)), strict=False)


def fragments_of(squashed: str) -> set[str]:
    if len(squashed) <= CANARY_FRAGMENT_CHARS:
        return {squashed}
    return {
        squashed[start : start + CANARY_FRAGMENT_CHARS] for start in range(len(squashed) - CANARY_FRAGMENT_CHARS + 1)
    }


def base64_fragments(canary: str) -> set[str]:
    fragments: set[str] = set()
    raw = canary.encode("utf-8")
    for shift, dropped_front in ((0, 0), (1, 2), (2, 3)):
        encoded = base64.b64encode(b"\x00" * shift + raw).decode("ascii").rstrip("=")
        stable = encoded[dropped_front:-2]
        fragments.add(stable)
        fragments.add(stable.translate(str.maketrans("+/", "-_")))
    return fragments


class OutputScanner:
    def __init__(
        self,
        prompts: Sequence[ActivePrompt],
        skills: Sequence[LoadedSkill] = (),
        extra_texts: Sequence[str] = (),
    ) -> None:
        canaries = {prompt.canary for prompt in prompts if prompt.canary}
        squashed = {squash(canary) for canary in canaries}
        self._fragments = frozenset(
            fragment for value in squashed for variant in (value, value[::-1]) for fragment in fragments_of(variant)
        )
        self._hex_fragments = frozenset(canary.encode("utf-8").hex() for canary in canaries)
        self._base64_fragments = frozenset(fragment for canary in canaries for fragment in base64_fragments(canary))
        instruction_bodies = [prompt.body for prompt in prompts] + list(extra_texts)
        self._shingles = frozenset(shingle for body in instruction_bodies for shingle in shingles_of(words_of(body)))
        self._skill_shingles = frozenset(
            shingle for skill in skills for shingle in shingles_of(words_of(skill.body), SKILL_OVERLAP_WORDS)
        )

    def contains_canary(self, text: str) -> bool:
        squashed = squash(text)
        if any(fragment in squashed for fragment in self._fragments):
            return True
        compact = "".join(text.split())
        if any(fragment in compact for fragment in self._base64_fragments):
            return True
        hexadecimal = "".join(character for character in text.lower() if character in "0123456789abcdef")
        return any(fragment in hexadecimal for fragment in self._hex_fragments)

    def overlaps_instructions(self, text: str) -> bool:
        words = words_of(text)
        if self._shingles and any(shingle in self._shingles for shingle in shingles_of(words)):
            return True
        return bool(self._skill_shingles) and any(
            shingle in self._skill_shingles for shingle in shingles_of(words, SKILL_OVERLAP_WORDS)
        )

    def overlaps_prompts(self, text: str) -> bool:
        return bool(self._shingles) and any(shingle in self._shingles for shingle in shingles_of(words_of(text)))

    def scan_text(self, text: str) -> ScanResult:
        if self.contains_canary(text):
            return ScanResult("canary")
        if self.overlaps_instructions(text):
            return ScanResult("overlap")
        return ScanResult()

    def scan_code(self, text: str) -> ScanResult:
        if self.contains_canary(text):
            return ScanResult("canary")
        return ScanResult()

    def scan_scene(self, code: str, literals: str) -> ScanResult:
        result = self.scan_code(code)
        if result.blocked:
            return result
        if self.overlaps_prompts(literals):
            return ScanResult("overlap")
        return ScanResult()

    def ensure_clean_scene(self, code: str, literals: str, *, source: str) -> str:
        return self.ensure(self.scan_scene(code, literals), code, source)

    def ensure_clean_text(self, text: str, *, source: str) -> str:
        return self.ensure(self.scan_text(text), text, source)

    def ensure_clean_code(self, text: str, *, source: str) -> str:
        return self.ensure(self.scan_code(text), text, source)

    @staticmethod
    def ensure(result: ScanResult, text: str, source: str) -> str:
        if result.kind is not None:
            logger.warning("ai.output_blocked", source=source, kind=result.kind)
            raise OutputBlockedError
        return text
