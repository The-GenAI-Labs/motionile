import base64
import binascii
import codecs
import re
import unicodedata
from dataclasses import dataclass
from typing import Final, Literal

from motionile.engine.ai.guardrails.personal_data import contains_personal_data
from motionile.engine.ai.guardrails.policy import PolicyCode
from motionile.engine.ai.prompts.delimit import DATA_TAGS

type InputKind = Literal["query", "storyboard_edit", "instructions"]
type Pattern = re.Pattern[str]

MIN_TEXT_CHARS: Final = 1
MAX_TEXT_CHARS: Final[dict[InputKind, int]] = {"query": 2_000, "instructions": 2_000, "storyboard_edit": 30_000}
MAX_DECODE_DEPTH: Final = 2
MIN_PRINTABLE_RATIO: Final = 0.9
MENTION_WINDOW: Final = 40

HIDDEN_CHARACTERS = re.compile(r"[\u200b\u2060-\u2064\u202a-\u202e\u2066-\u2069\ufeff\u180e\U000e0000-\U000e007f]")
HORIZONTAL_SPACE = re.compile(r"[ \t\f\v]+")
BASE64_TOKEN = re.compile(r"[A-Za-z0-9+/_-]{24,}={0,2}")
HEX_RUN = re.compile(r"(?:[0-9a-fA-F]{2}[ :]?){24,}")
OBFUSCATION_HINT = re.compile(r"\b(?:rot-?13|caesar|cipher)\b", re.IGNORECASE)
MENTION_CONTEXT = re.compile(
    r"""(?:["'`\u201c\u201d\u2018\u2019\u00ab\u00bb]"""
    r"""|\b(?:phrases?|words?|text|string|sentence|command|called|titled|saying|says|said|like|such as|terms?)"""
    r"""\s*:?)\s*$""",
    re.IGNORECASE,
)

INSTRUCTION_NOUNS = (
    r"(?:instructions?|prompts?|directions?|guidelines?|commands?|constraints?|restrictions?|directives?)"
)
SENTENCE_START = r"(?:^|[\n.!?:]\s*)"
TAG_ALTERNATION = "|".join(DATA_TAGS)
ROLE_TAGS = r"(?:system|assistant|developer)"
PROMPT_WORDS = (
    r"(?:prompts?|instructions?|rules|guidelines|configuration|config|directives|skills?|canary|marker|programming)"
)
PROMPT_ADJECTIVES = (
    r"(?:(?:full|complete|entire|original|initial|hidden|secret|internal|system|developer|exact|verbatim|raw)\s+)*"
)
EXTRACTION_VERBS = (
    r"(?:reveal|show|print|display|repeat|output|tell|give|send|leak|dump|share|recite|echo|paste|copy|list|"
    r"disclose|expose|read|spell|write|summari[sz]e|translate)"
)


@dataclass(frozen=True, slots=True)
class Rule:
    code: PolicyCode
    name: str
    pattern: Pattern
    mention_exempt: bool = True


@dataclass(frozen=True, slots=True)
class RuleVerdict:
    code: PolicyCode
    rule: str


def compile_rule(code: PolicyCode, name: str, pattern: str, *, mention_exempt: bool = True) -> Rule:
    return Rule(code, name, re.compile(pattern, re.IGNORECASE | re.MULTILINE), mention_exempt)


INJECTION_RULES: Final = (
    compile_rule(
        PolicyCode.PROMPT_INJECTION,
        "ignore_previous",
        r"\b(?:ignore|disregard|forget|discard|abandon)\b(?:\s+(?:all|any|every|the|your|my|these|those|of|what))*"
        rf"\s+(?:previous|prior|above|earlier|preceding|former|original|initial)\s+{INSTRUCTION_NOUNS}",
    ),
    compile_rule(
        PolicyCode.PROMPT_INJECTION,
        "ignore_your_rules",
        r"\b(?:ignore|disregard|forget|override|bypass|circumvent)\b\s+(?:"
        r"(?:your|my)\s+(?:(?:previous|prior|safety|system|existing)\s+)?"
        r"(?:instructions?|rules|guidelines|restrictions|programming|training|directives|constraints|policies|filters)"
        r"|(?:all|any|every|these|those)\s+(?:(?:previous|prior)\s+)?(?:instructions|guidelines|directives|programming))",
    ),
    compile_rule(
        PolicyCode.PROMPT_INJECTION,
        "forget_everything_above",
        r"\b(?:ignore|disregard|forget)\s+(?:everything|anything|all)\s+(?:above|before|you\s+(?:were\s+told|know)|said)",
    ),
    compile_rule(
        PolicyCode.PROMPT_INJECTION,
        "do_not_follow",
        r"\bdo\s+not\s+(?:follow|obey|apply)\s+"
        r"(?:your\s+(?:(?:previous|prior|system)\s+)?|(?:the\s+)?(?:previous|prior|system)\s+)"
        r"(?:instructions?|rules|guidelines)",
    ),
    compile_rule(
        PolicyCode.PROMPT_INJECTION,
        "role_change",
        r"\byou\s+are\s+now\s+(?:a|an|the|my|no\s+longer|free|unrestricted|dan)\b",
    ),
    compile_rule(
        PolicyCode.PROMPT_INJECTION,
        "from_now_on",
        r"\bfrom\s+now\s+on,?\s+(?:you|act|behave|respond|answer|ignore|only)\b",
    ),
    compile_rule(
        PolicyCode.PROMPT_INJECTION,
        "unrestricted_persona",
        r"\b(?:act|behave|respond|pretend|roleplay)\b[^.\n]{0,20}\b(?:as|like)\b[^.\n]{0,20}"
        r"\b(?:unrestricted|unfiltered|uncensored|jailbroken|evil|dan)\b",
    ),
    compile_rule(
        PolicyCode.PROMPT_INJECTION,
        "no_rules_persona",
        r"\bpretend\s+(?:that\s+)?you\s+(?:are|have|were)\s+(?:no|without)\s+(?:rules|restrictions|guidelines|filters)",
    ),
    compile_rule(PolicyCode.PROMPT_INJECTION, "do_anything_now", r"\bdo\s+anything\s+now\b"),
    compile_rule(
        PolicyCode.PROMPT_INJECTION,
        "developer_mode_state",
        r"\byou\s+(?:are|'re)\s+(?:now\s+)?in\s+(?:developer|debug|admin|god|dan|jailbreak|sudo)\s+mode\b"
        r"|\b(?:developer|debug|jailbreak|god)\s+mode\s+(?:enabled|activated)\b",
    ),
    compile_rule(PolicyCode.PROMPT_INJECTION, "jailbreak_header", rf"{SENTENCE_START}jailbreak\s*[:\-]"),
    compile_rule(
        PolicyCode.PROMPT_INJECTION,
        "disable_safety",
        r"\b(?:disable|turn\s+off|remove|switch\s+off)\s+(?:all\s+|your\s+|the\s+)?(?:safety|content)\s+"
        r"(?:filters?|checks?|guardrails?|rules?|policies)",
    ),
    compile_rule(
        PolicyCode.PROMPT_INJECTION,
        "new_instructions",
        r"\b(?:new|updated|real|actual|override)\s+(?:system\s+)?instructions?\s*:"
        r"|\bend\s+of\s+(?:the\s+)?(?:system\s+)?(?:prompt|instructions?)\b",
    ),
    compile_rule(
        PolicyCode.PROMPT_INJECTION,
        "decode_and_follow",
        r"\b(?:decode|decrypt|deobfuscate|unscramble)\b[^.\n]{0,60}\b(?:and|then)\s+(?:follow|obey|execute|run|do|apply)\s+"
        r"(?:it|them|that|this|whatever|what\b|the\s+(?:instructions?|text|message|commands?))",
    ),
    compile_rule(
        PolicyCode.PROMPT_INJECTION,
        "code_fence_role",
        rf"```\s*(?:{ROLE_TAGS}|instructions?)\b",
        mention_exempt=False,
    ),
    compile_rule(
        PolicyCode.PROMPT_INJECTION,
        "delimiter_spoofing",
        rf"(?:<|&lt;|&#0*60;|&#x0*3c;)\s*/?\s*(?:{TAG_ALTERNATION})\b",
        mention_exempt=False,
    ),
    compile_rule(
        PolicyCode.PROMPT_INJECTION,
        "chat_template_tokens",
        r"<\|[^|>\n]{1,30}\|>|\[/?\s*inst\s*\]|<<\s*/?\s*sys\s*>>"
        rf"|(?:<|&lt;)\s*/?\s*{ROLE_TAGS}\s*(?:>|&gt;)",
        mention_exempt=False,
    ),
    compile_rule(
        PolicyCode.PROMPT_INJECTION,
        "role_line",
        rf"^\s*(?:#{{1,3}}\s*)?{ROLE_TAGS}\s*:\s*(?:you|ignore|new|from|your|do|always|never|respond|reply|output|act)\b",
        mention_exempt=False,
    ),
)

EXTRACTION_RULES: Final = (
    compile_rule(
        PolicyCode.PROMPT_EXTRACTION,
        "reveal_your_prompt",
        rf"\b{EXTRACTION_VERBS}\b(?:\s+(?:me|us|out|back))*\s+(?:all\s+|exactly\s+)?(?:of\s+)?"
        rf"(?:your|motionile'?s?|its)\s+(?:own\s+)?{PROMPT_ADJECTIVES}{PROMPT_WORDS}",
    ),
    compile_rule(
        PolicyCode.PROMPT_EXTRACTION,
        "what_are_your_instructions",
        rf"\bwhat\s+(?:is|are|were|was)\s+your\s+{PROMPT_ADJECTIVES}{PROMPT_WORDS}",
    ),
    compile_rule(
        PolicyCode.PROMPT_EXTRACTION,
        "repeat_above",
        r"\b(?:repeat|print|output|copy|reproduce|recite|echo|say)\b[^.\n]{0,25}"
        r"\b(?:text|words|content|everything|message|messages|instructions?|prompt)\s+"
        r"(?:above|before\s+this|so\s+far|at\s+the\s+(?:top|start|beginning))"
        r"|\b(?:repeat|print|output|copy|reproduce)\s+(?:everything|all)\s+(?:above|before|from\s+the\s+beginning)",
    ),
    compile_rule(
        PolicyCode.PROMPT_EXTRACTION,
        "begin_with_prompt",
        r"\b(?:begin|start)\s+(?:your\s+)?(?:response|answer|reply)\s+with\s+(?:your|the)\s+"
        r"(?:system|initial|hidden)\s+(?:prompt|instructions)",
    ),
    compile_rule(
        PolicyCode.PROMPT_EXTRACTION,
        "internal_marker",
        r"\binternal\s+marker\b|mo-canary",
        mention_exempt=False,
    ),
)

TEXT_RULES: Final = (*INJECTION_RULES, *EXTRACTION_RULES)


def matchable(text: str) -> str:
    folded = unicodedata.normalize("NFKC", HIDDEN_CHARACTERS.sub("", text))
    return HORIZONTAL_SPACE.sub(" ", folded)


def is_mention(text: str, start: int) -> bool:
    return MENTION_CONTEXT.search(text[max(0, start - MENTION_WINDOW) : start]) is not None


def matching_rule(text: str) -> Rule | None:
    for rule in TEXT_RULES:
        for match in rule.pattern.finditer(text):
            if rule.mention_exempt and is_mention(text, match.start()):
                continue
            return rule
    return None


def printable_ratio(text: str) -> float:
    if not text:
        return 0.0
    printable = sum(1 for character in text if character.isprintable() or character in "\n\t")
    return printable / len(text)


def decode_base64(token: str) -> str | None:
    padded = token + "=" * (-len(token) % 4)
    try:
        raw = base64.b64decode(padded.replace("-", "+").replace("_", "/"), validate=True)
        decoded = raw.decode("utf-8")
    except (binascii.Error, ValueError):
        return None
    return decoded if printable_ratio(decoded) >= MIN_PRINTABLE_RATIO else None


def decode_hex(run: str) -> str | None:
    digits = re.sub(r"[ :]", "", run)
    try:
        decoded = bytes.fromhex(digits).decode("utf-8")
    except ValueError:
        return None
    return decoded if printable_ratio(decoded) >= MIN_PRINTABLE_RATIO else None


def hidden_instruction_rule(text: str, depth: int = 0) -> Rule | None:
    if depth >= MAX_DECODE_DEPTH:
        return None
    candidates = [decode_base64(token) for token in BASE64_TOKEN.findall(text)]
    candidates.extend(decode_hex(run) for run in HEX_RUN.findall(text))
    if OBFUSCATION_HINT.search(text):
        candidates.append(codecs.decode(text, "rot13"))
    for decoded in candidates:
        if decoded is None:
            continue
        normalized = matchable(decoded)
        found = matching_rule(normalized) or hidden_instruction_rule(normalized, depth + 1)
        if found is not None:
            return found
    return None


def length_verdict(text: str, kind: InputKind) -> RuleVerdict | None:
    stripped = text.strip()
    if len(stripped) < MIN_TEXT_CHARS:
        return RuleVerdict(PolicyCode.UNSUPPORTED_REQUEST, "empty")
    if len(stripped) > MAX_TEXT_CHARS[kind]:
        return RuleVerdict(PolicyCode.UNSUPPORTED_REQUEST, "too_long")
    if not any(character.isalnum() for character in stripped):
        return RuleVerdict(PolicyCode.UNSUPPORTED_REQUEST, "no_content")
    return None


def character_verdict(text: str) -> RuleVerdict | None:
    if HIDDEN_CHARACTERS.search(text.removeprefix("\ufeff")):
        return RuleVerdict(PolicyCode.PROMPT_INJECTION, "hidden_characters")
    if any(unicodedata.category(character) == "Cc" and character not in "\n\r\t" for character in text):
        return RuleVerdict(PolicyCode.UNSUPPORTED_REQUEST, "control_characters")
    return None


def injection_verdict(text: str) -> RuleVerdict | None:
    normalized = matchable(text)
    rule = matching_rule(normalized) or hidden_instruction_rule(normalized)
    if rule is None:
        return None
    return RuleVerdict(rule.code, rule.name)


def personal_data_verdict(text: str) -> RuleVerdict | None:
    if contains_personal_data(text):
        return RuleVerdict(PolicyCode.PERSONAL_DATA, "personal_data")
    return None


def run_input_rules(text: str, kind: InputKind) -> RuleVerdict | None:
    return (
        length_verdict(text, kind) or character_verdict(text) or injection_verdict(text) or personal_data_verdict(text)
    )
