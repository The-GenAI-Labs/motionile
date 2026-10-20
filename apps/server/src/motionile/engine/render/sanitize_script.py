import re
from dataclasses import dataclass

COMPOSITION_CALL = re.compile(r"\bMotionile\s*\.\s*composition\s*\(")
LINE_COMMENT = r"//[^\n]*"
BLOCK_COMMENT = r"/\*.*?\*/"
DOUBLE_QUOTED = r'"(?:\\.|[^"\\\n])*"'
SINGLE_QUOTED = r"'(?:\\.|[^'\\\n])*'"
TEMPLATE_LITERAL = r"`(?:\\.|[^`\\])*`"
NOISE = re.compile(
    "|".join((LINE_COMMENT, BLOCK_COMMENT, DOUBLE_QUOTED, SINGLE_QUOTED, TEMPLATE_LITERAL)),
    re.DOTALL,
)


@dataclass(frozen=True)
class ScriptPattern:
    name: str
    expression: re.Pattern[str]


def pattern(name: str, expression: str) -> ScriptPattern:
    return ScriptPattern(name, re.compile(expression))


SCRIPT_PATTERNS: tuple[ScriptPattern, ...] = (
    pattern("fetch", r"(?<![\w$.])fetch\s*\(|\b(?:window|self|globalThis)\s*\.\s*fetch\b"),
    pattern("XMLHttpRequest", r"\bXMLHttpRequest\b"),
    pattern("WebSocket", r"\bWebSocket\b"),
    pattern("EventSource", r"\bEventSource\b"),
    pattern("sendBeacon", r"\bsendBeacon\b"),
    pattern("eval", r"(?<![\w$.])eval\s*\("),
    pattern("Function", r"\bnew\s+Function\b|(?<![\w$.])Function\s*\("),
    pattern("import()", r"(?<![\w$.])import\s*\("),
    pattern("importScripts", r"\bimportScripts\b"),
    pattern("Worker", r"\b(?:Worker|Worklet)\b"),
    pattern("SharedWorker", r"\bSharedWorker\b"),
    pattern("serviceWorker", r"\bserviceWorker\b"),
    pattern("storage", r"\b(?:localStorage|sessionStorage|indexedDB|caches|cookieStore)\b"),
    pattern("cookie", r"\bdocument\s*\.\s*cookie\b"),
    pattern("window.open", r"\b(?:window|self|top|parent|globalThis)\s*\.\s*open\s*\("),
    pattern(
        "location",
        r"\b(?:window\s*\.\s*|document\s*\.\s*|top\s*\.\s*|parent\s*\.\s*|self\s*\.\s*)?location\s*"
        r"(?:\.\s*(?:href|assign|replace|reload)\b|=(?!=))",
    ),
    pattern("history", r"\bhistory\s*\.\s*(?:pushState|replaceState|go|back|forward)\b"),
    pattern("RTCPeerConnection", r"\b(?:webkit)?RTCPeerConnection\b"),
    pattern("computed window access", r"\b(?:window|globalThis|self|top|parent)\s*\["),
)


@dataclass(frozen=True)
class ScriptHit:
    name: str
    excerpt: str


def replace_noise(match: re.Match[str]) -> str:
    text = match.group(0)
    return " " if text.startswith("/") else text[0] * 2


def strip_noise(source: str) -> str:
    return NOISE.sub(replace_noise, source)


def count_composition_calls(source: str) -> int:
    return len(COMPOSITION_CALL.findall(strip_noise(source)))


def screen_script(source: str) -> list[ScriptHit]:
    cleaned = strip_noise(source)
    hits: list[ScriptHit] = []
    for candidate in SCRIPT_PATTERNS:
        match = candidate.expression.search(cleaned)
        if match is not None:
            start = max(0, match.start() - 20)
            excerpt = " ".join(cleaned[start : match.end() + 40].split())
            hits.append(ScriptHit(candidate.name, excerpt))
    return hits
