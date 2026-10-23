import base64
import binascii
import posixpath
import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import unquote, urljoin, urlsplit

from motionile.engine.render.runtime import COMPOSITION_URL, RUNTIME_BASE_PATH, RUNTIME_HOST

DATA_SCHEME = "data:"
JAVASCRIPT_SCHEME = "javascript"
IGNORED_URL_CHARACTERS = re.compile(r"[\t\n\r]")
CONTROL_AND_SPACE_EDGES = re.compile(r"^[\x00-\x20]+|[\x00-\x20]+$")
BASE64_WHITESPACE = re.compile(r"[\t\n\f\r ]+")
ALLOWED_DATA_TYPES = frozenset(
    {
        "application/font-woff",
        "application/font-woff2",
        "application/x-font-ttf",
        "application/x-font-woff",
        "application/vnd.ms-fontobject",
    }
)
TEXT_DATA_TYPES = frozenset({"image/svg+xml"})
SNIPPET_LENGTH = 120
RUNTIME_REASON = "runtime asset"


class UrlVerdict(StrEnum):
    ALLOWED = "allowed"
    FORBIDDEN = "forbidden"
    INVALID_DATA = "invalid_data"


@dataclass(frozen=True)
class UrlCheck:
    verdict: UrlVerdict
    reason: str
    data_bytes: int = 0

    @property
    def allowed(self) -> bool:
        return self.verdict is UrlVerdict.ALLOWED


def snippet(value: str) -> str:
    collapsed = " ".join(value.split())
    return collapsed if len(collapsed) <= SNIPPET_LENGTH else collapsed[:SNIPPET_LENGTH] + "..."


def normalize_url(value: str) -> str:
    stripped = CONTROL_AND_SPACE_EDGES.sub("", value)
    return IGNORED_URL_CHARACTERS.sub("", stripped).replace("\\", "/")


def is_data_media_type_allowed(media_type: str) -> bool:
    return media_type.startswith(("image/", "font/")) or media_type in ALLOWED_DATA_TYPES


def check_data_uri(normalized: str) -> UrlCheck:
    size = len(normalized)
    header, separator, payload = normalized[len(DATA_SCHEME) :].partition(",")
    if not separator:
        return UrlCheck(UrlVerdict.INVALID_DATA, "data URI has no payload", size)
    parameters = [part.strip().lower() for part in header.split(";")]
    media_type = parameters[0] or "text/plain"
    is_base64 = "base64" in parameters[1:]
    if not is_data_media_type_allowed(media_type):
        return UrlCheck(UrlVerdict.INVALID_DATA, f"data URI media type {media_type} is not an image or font", size)
    if is_base64:
        try:
            base64.b64decode(BASE64_WHITESPACE.sub("", unquote(payload)), validate=True)
        except (binascii.Error, ValueError):
            return UrlCheck(UrlVerdict.INVALID_DATA, "data URI is not valid base64", size)
        return UrlCheck(UrlVerdict.ALLOWED, "data image or font", size)
    if media_type not in TEXT_DATA_TYPES:
        return UrlCheck(UrlVerdict.INVALID_DATA, "data URI that is not base64 must be image/svg+xml", size)
    return UrlCheck(UrlVerdict.ALLOWED, "data svg image", size)


def is_runtime_path(path: str) -> bool:
    decoded = unquote(path)
    normalized = posixpath.normpath(decoded)
    return normalized.startswith(RUNTIME_BASE_PATH.rstrip("/") + "/")


def check_remote_url(normalized: str) -> UrlCheck:
    try:
        parts = urlsplit(normalized)
        resolved = urlsplit(urljoin(COMPOSITION_URL, normalized))
        port = resolved.port
    except ValueError:
        return UrlCheck(UrlVerdict.FORBIDDEN, "the URL cannot be parsed")
    if parts.scheme.lower() == JAVASCRIPT_SCHEME:
        return UrlCheck(UrlVerdict.FORBIDDEN, "javascript: URL")
    if resolved.scheme != "https":
        return UrlCheck(UrlVerdict.FORBIDDEN, f"scheme {resolved.scheme or 'unknown'} is not allowed")
    if resolved.hostname != RUNTIME_HOST or resolved.username is not None or port not in (None, 443):
        return UrlCheck(UrlVerdict.FORBIDDEN, "the URL is outside the runtime origin")
    if not is_runtime_path(resolved.path):
        return UrlCheck(UrlVerdict.FORBIDDEN, "the URL is outside the runtime path")
    return UrlCheck(UrlVerdict.ALLOWED, RUNTIME_REASON)


def check_url(value: str) -> UrlCheck:
    normalized = normalize_url(value)
    if normalized == "" or normalized.startswith("#"):
        return UrlCheck(UrlVerdict.ALLOWED, "empty or fragment")
    if normalized.lower().startswith(DATA_SCHEME):
        return check_data_uri(normalized)
    return check_remote_url(normalized)


def is_runtime_url(value: str) -> bool:
    check = check_url(value)
    return check.allowed and check.reason == RUNTIME_REASON


def split_srcset(value: str) -> list[str]:
    urls: list[str] = []
    position = 0
    length = len(value)
    while position < length:
        while position < length and (value[position].isspace() or value[position] == ","):
            position += 1
        start = position
        while position < length and not value[position].isspace():
            position += 1
        candidate = value[start:position]
        if not candidate:
            break
        urls.append(candidate.rstrip(","))
        if candidate.endswith(","):
            continue
        depth = 0
        while position < length:
            character = value[position]
            if character == "(":
                depth += 1
            elif character == ")":
                depth = max(0, depth - 1)
            elif character == "," and depth == 0:
                break
            position += 1
    return urls
