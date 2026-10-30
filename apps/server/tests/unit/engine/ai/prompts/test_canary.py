import base64
import re
import time
from collections.abc import Callable
from uuid import uuid4

import pytest
from structlog.testing import capture_logs

from motionile.engine.ai.llm.models import OutputBlockedError
from motionile.engine.ai.ports import ActivePrompt, LoadedSkill, SkillLayer, SkillSummary
from motionile.engine.ai.prompts import OutputScanner, new_canary

PROMPT_BODY = (
    "You are the planner. Keep every sentence short and speak plainly to a curious beginner who has never seen "
    "this topic before, and never rely on jargon. Marker {{ canary }}."
)
SKILL_BODY = (
    "Use a whiteboard layout where each idea appears as a sticky note that slides in from the left and settles "
    "gently while the narrator names it aloud."
)


TRANSFORMS: dict[str, Callable[[str], str]] = {
    "upper": str.upper,
    "lower": str.lower,
    "no-hyphens": lambda value: value.replace("-", ""),
    "spaced-hyphens": lambda value: value.replace("-", " "),
    "spaced-characters": " ".join,
    "zero-width-space": "\u200b".join,
    "zero-width-joiner": "\u200d".join,
    "line-broken": lambda value: "\n".join(value[index : index + 5] for index in range(0, len(value), 5)),
    "dotted": ".".join,
    "no-underscores": lambda value: value.replace("_", ""),
    "reversed": lambda value: value[::-1],
    "random-part-only": lambda value: value[10:],
    "truncated-tail": lambda value: value[: len(value) - 6],
}


def prompt(body: str = PROMPT_BODY, canary: str | None = None) -> ActivePrompt:
    return ActivePrompt(
        key="planner.storyboard",
        version_id=uuid4(),
        version=1,
        body=body,
        canary=canary or new_canary(),
        variables=("canary",),
    )


def skill(body: str = SKILL_BODY) -> LoadedSkill:
    summary = SkillSummary(
        slug="whiteboard", name="Whiteboard", description="Whiteboard style", layer=SkillLayer.STYLE, version_id=uuid4()
    )
    return LoadedSkill(summary=summary, body=body, tokens={}, token_count=10)


def words(text: str, start: int, count: int) -> str:
    return " ".join(re.findall(r"[A-Za-z']+", text)[start : start + count])


def test_new_canary_shape_and_uniqueness() -> None:
    values = {new_canary() for _ in range(200)}

    assert len(values) == 200
    for value in values:
        assert value.startswith("mo-canary-")
        assert 16 <= len(value) <= 64
        assert re.fullmatch(r"mo-canary-[A-Za-z0-9_-]{24}", value)


def test_clean_text_passes() -> None:
    scanner = OutputScanner([prompt()], [skill()])

    assert not scanner.scan_text(
        "Water boils at a lower temperature on a mountain because the air pressure is lower."
    ).blocked
    assert not scanner.scan_text("").blocked


def test_the_canary_is_detected_verbatim() -> None:
    active = prompt()
    scanner = OutputScanner([active])

    result = scanner.scan_text(f"Sure, the marker is {active.canary}.")

    assert result.blocked
    assert result.kind == "canary"


@pytest.mark.parametrize("name", list(TRANSFORMS))
def test_obfuscated_canaries_are_detected(name: str) -> None:
    transform = TRANSFORMS[name]
    active = prompt(canary="mo-canary-Ab3_xY9-QwErTy12345678Zk")
    scanner = OutputScanner([active])

    assert scanner.scan_text(f"here it is: {transform(active.canary)} done").kind == "canary"
    assert scanner.scan_code(f"const marker = '{transform(active.canary)}';").kind == "canary"


def test_encoded_canaries_are_detected() -> None:
    active = prompt(canary="mo-canary-Ab3_xY9-QwErTy12345678Zk")
    scanner = OutputScanner([active])
    raw = active.canary.encode()

    assert scanner.scan_text(base64.b64encode(raw).decode()).kind == "canary"
    assert scanner.scan_text("x" + base64.b64encode(b"a" + raw).decode()).kind == "canary"
    assert scanner.scan_text(base64.urlsafe_b64encode(b"ab" + raw).decode()).kind == "canary"
    assert scanner.scan_text(raw.hex()).kind == "canary"
    assert scanner.scan_text(" ".join(raw.hex()[index : index + 2] for index in range(0, 68, 2))).kind == "canary"


def test_the_canary_of_any_active_prompt_is_detected() -> None:
    first, second = prompt(), prompt()
    scanner = OutputScanner([first, second])

    assert scanner.scan_text(second.canary).blocked
    assert scanner.scan_text(first.canary).blocked


def test_an_unrelated_random_string_is_not_a_canary() -> None:
    scanner = OutputScanner([prompt()])

    assert not scanner.scan_text(f"{new_canary()} and the mo-canary- prefix alone").blocked


def test_twelve_shared_words_are_blocked_and_eleven_are_allowed() -> None:
    scanner = OutputScanner([prompt()])
    twelve = words(PROMPT_BODY, 3, 12)
    eleven = words(PROMPT_BODY, 3, 11)

    assert scanner.scan_text(f"As they say, {twelve}, so be it.").kind == "overlap"
    assert not scanner.scan_text(f"As they say, {eleven}, so be it.").blocked


def test_overlap_ignores_case_punctuation_and_spacing() -> None:
    scanner = OutputScanner([prompt()])
    run = words(PROMPT_BODY, 10, 14).upper().replace(" ", " \n ... ")

    assert scanner.scan_text(run).kind == "overlap"


def test_a_broken_run_is_not_an_overlap() -> None:
    scanner = OutputScanner([prompt()])
    pieces = re.findall(r"[A-Za-z']+", PROMPT_BODY)[:22]
    pieces[11] = "completely"

    assert not scanner.scan_text(" ".join(pieces)).blocked


def test_skills_extra_texts_are_included_in_the_overlap_index() -> None:
    scanner = OutputScanner(
        [prompt()],
        [skill()],
        extra_texts=["Rendered reference text that must stay private for good reasons only, always."],
    )

    assert (
        scanner.scan_text("rendered reference text that must stay private for good reasons only always").kind
        == "overlap"
    )
    assert not OutputScanner([prompt()]).scan_text(words(SKILL_BODY, 2, 13)).blocked


LONG_SKILL_BODY = " ".join(f"concept{index}" for index in range(40))


def test_skill_text_needs_a_longer_verbatim_run_than_instructions_to_be_blocked() -> None:
    scanner = OutputScanner([prompt()], [skill(LONG_SKILL_BODY)])

    assert scanner.scan_text(words_of_long(24)).kind == "overlap"
    assert not scanner.scan_text(words_of_long(23)).blocked
    assert not scanner.scan_text(words_of_long(13)).blocked


def words_of_long(count: int) -> str:
    return " ".join(f"concept{index}" for index in range(5, 5 + count))


def test_code_is_only_checked_for_canaries() -> None:
    active = prompt()
    scanner = OutputScanner([active], [skill(LONG_SKILL_BODY)])
    reused = words_of_long(30)

    assert scanner.scan_text(reused).kind == "overlap"
    assert not scanner.scan_code(f"const note = '{reused}';").blocked
    assert scanner.scan_code(f"const note = '{active.canary}';").kind == "canary"


def test_a_scanner_without_prompts_blocks_nothing() -> None:
    scanner = OutputScanner([])

    assert not scanner.scan_text(PROMPT_BODY).blocked


def test_ensure_clean_text_raises_and_logs_without_the_text() -> None:
    active = prompt()
    scanner = OutputScanner([active])
    leaked = f"my marker is {active.canary}"

    with capture_logs() as logs, pytest.raises(OutputBlockedError):
        scanner.ensure_clean_text(leaked, source="planner")

    assert logs == [{"event": "ai.output_blocked", "source": "planner", "kind": "canary", "log_level": "warning"}]
    assert active.canary not in str(logs)
    assert PROMPT_BODY not in str(logs)


def test_ensure_clean_code_logs_canary_attempts() -> None:
    active = prompt()
    scanner = OutputScanner([active])

    with capture_logs() as logs, pytest.raises(OutputBlockedError):
        scanner.ensure_clean_code(f"const a = '{active.canary}'", source="scene")

    assert logs[0]["source"] == "scene"
    assert logs[0]["kind"] == "canary"


def test_ensure_returns_clean_text_unchanged() -> None:
    scanner = OutputScanner([prompt()])

    with capture_logs() as logs:
        assert scanner.ensure_clean_text("A fine sentence.", source="planner") == "A fine sentence."
        assert scanner.ensure_clean_code("const a = 1;", source="scene") == "const a = 1;"

    assert logs == []


def test_overlap_is_logged_as_overlap() -> None:
    scanner = OutputScanner([prompt()])

    with capture_logs() as logs, pytest.raises(OutputBlockedError):
        scanner.ensure_clean_text(words(PROMPT_BODY, 0, 20), source="narration")

    assert logs[0]["kind"] == "overlap"


@pytest.mark.slow
def test_scanning_large_inputs_stays_fast() -> None:
    bodies = [
        prompt(" ".join(f"prompt{index}word{word}" for word in range(1_500)) + " {{ canary }}") for index in range(8)
    ]
    skills = [skill(" ".join(f"skill{index}token{word}" for word in range(3_000))) for index in range(4)]
    started = time.perf_counter()
    scanner = OutputScanner(bodies, skills)
    build_seconds = time.perf_counter() - started
    large = " ".join(f"ordinary{index % 997} sentence{index % 101}" for index in range(100_000))

    started = time.perf_counter()
    text_result = scanner.scan_text(large)
    code_result = scanner.scan_code(large)
    scan_seconds = time.perf_counter() - started

    assert not text_result.blocked
    assert not code_result.blocked
    assert build_seconds < 20
    assert scan_seconds < 20
