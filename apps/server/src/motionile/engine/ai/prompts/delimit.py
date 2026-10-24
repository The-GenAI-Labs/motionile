import re

DATA_TAGS: tuple[str, ...] = (
    "user_query",
    "storyboard_edit",
    "revision_instructions",
    "narration",
    "previous_attempt",
    "issues",
    "context",
)

JOINERS = "[\u200c\u200d]*"
OPENERS = r"(?:<|\uff1c|\ufe64|&lt;|&#0*60;|&#x0*3c;)"
TAG_NAMES = "|".join(JOINERS.join(re.escape(character) for character in tag) for tag in DATA_TAGS)
TAG_LIKE = re.compile(rf"({OPENERS})(?=\s*{JOINERS}/?\s*{JOINERS}(?:{TAG_NAMES})(?![a-z0-9]))", re.IGNORECASE)
INVISIBLE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u00ad\u200b\u200e\u200f\u202a-\u202e"
    r"\u2060-\u2064\u2066-\u2069\ufeff\U000e0000-\U000e007f]"
)
SAFE_OPENER = "\u2039"


def neutralize(text: str) -> str:
    return TAG_LIKE.sub(SAFE_OPENER, INVISIBLE.sub("", text))


def delimit(tag: str, text: str) -> str:
    if tag not in DATA_TAGS:
        raise ValueError(f"unknown data tag: {tag}")
    return f"<{tag}>\n{neutralize(text)}\n</{tag}>"
