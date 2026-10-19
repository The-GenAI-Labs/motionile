from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Literal

from motionile.engine.audio.models import WordTiming

type Aspect = Literal["16:9", "9:16", "1:1"]


def characters_of(*codepoints: int) -> frozenset[str]:
    return frozenset(chr(codepoint) for codepoint in codepoints)


SENTENCE_ENDINGS = characters_of(0x2E, 0x21, 0x3F, 0x964, 0x965, 0x2026, 0x3002, 0xFF01, 0xFF1F)
CLAUSE_ENDINGS = characters_of(0x2C, 0x3B, 0x3A, 0x2014, 0x2013, 0xFF0C, 0xFF1B, 0xFF1A)
CLOSING_CHARACTERS = characters_of(0x22, 0x27, 0x201D, 0x2019, 0x29, 0x5D, 0x7D, 0xBB)
MAX_LINES = 2
ELLIPSIS = chr(0x2026)
DEVANAGARI_START = 0x0900
DEVANAGARI_END = 0x097F
MS_PER_SECOND = 1000
MS_PER_MINUTE = 60 * MS_PER_SECOND
MS_PER_HOUR = 60 * MS_PER_MINUTE
MS_PER_CENTISECOND = 10
LATIN_STYLE = "Default"
DEVANAGARI_STYLE = "Devanagari"
BOX_COLOUR = "&H66000000"
TEXT_COLOUR = "&H00FFFFFF"
ASPECT_ALIASES: dict[str, Aspect] = {
    "16:9": "16:9",
    "16x9": "16:9",
    "9:16": "9:16",
    "9x16": "9:16",
    "1:1": "1:1",
    "1x1": "1:1",
}


@dataclass(frozen=True, slots=True)
class CueSettings:
    max_line_chars: int = 42
    min_duration_ms: int = 1000
    max_duration_ms: int = 6000
    pause_break_ms: int = 350
    end_padding_ms: int = 120
    clause_break_min_chars: int = 14


@dataclass(frozen=True, slots=True)
class Cue:
    index: int
    start_ms: int
    end_ms: int
    lines: tuple[str, ...]
    first_word: int
    end_word: int

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass(frozen=True, slots=True)
class CaptionLayout:
    width: int
    height: int
    band_px: int
    font_size: int
    margin_v: int
    margin_h: int
    box_padding: int

    @property
    def block_height(self) -> int:
        return round(MAX_LINES * self.font_size * 1.25) + 2 * self.box_padding


CAPTION_LAYOUTS: dict[Aspect, CaptionLayout] = {
    "16:9": CaptionLayout(1920, 1080, band_px=160, font_size=48, margin_v=12, margin_h=96, box_padding=10),
    "9:16": CaptionLayout(1080, 1920, band_px=420, font_size=36, margin_v=220, margin_h=72, box_padding=10),
    "1:1": CaptionLayout(1080, 1080, band_px=200, font_size=36, margin_v=50, margin_h=72, box_padding=10),
}


def parse_aspect(label: str) -> Aspect:
    aspect = ASPECT_ALIASES.get(label)
    if aspect is None:
        raise ValueError(f"unsupported aspect {label!r}")
    return aspect


def trimmed_ending(text: str) -> str:
    stripped = text.rstrip("".join(CLOSING_CHARACTERS))
    return stripped[-1] if stripped else ""


def ends_sentence(text: str) -> bool:
    return trimmed_ending(text) in SENTENCE_ENDINGS


def ends_clause(text: str) -> bool:
    return trimmed_ending(text) in CLAUSE_ENDINGS


def hard_split(token: str, width: int) -> tuple[str, ...]:
    limit = MAX_LINES * width
    shortened = token if len(token) <= limit else token[: limit - 1] + ELLIPSIS
    return tuple(shortened[offset : offset + width] for offset in range(0, len(shortened), width))


def layout_lines(words: Sequence[str], width: int) -> tuple[str, ...] | None:
    joined = " ".join(words)
    if len(joined) <= width:
        return (joined,)
    if len(words) == 1:
        return hard_split(words[0], width)
    best: tuple[str, str] | None = None
    for split in range(1, len(words)):
        first, second = " ".join(words[:split]), " ".join(words[split:])
        if len(first) > width or len(second) > width:
            continue
        if best is None or max(len(first), len(second)) < max(len(best[0]), len(best[1])):
            best = (first, second)
    return best


def span_fits(words: Sequence[WordTiming], settings: CueSettings) -> bool:
    if layout_lines([word.text for word in words], settings.max_line_chars) is None:
        return False
    duration = words[-1].end_ms + settings.end_padding_ms - words[0].start_ms
    return duration <= settings.max_duration_ms or len(words) == 1


def breaks_after(words: Sequence[WordTiming], start: int, end: int, settings: CueSettings) -> bool:
    current, following = words[end - 1], words[end]
    if ends_sentence(current.text):
        return True
    if following.start_ms - current.end_ms >= settings.pause_break_ms:
        return True
    characters = len(" ".join(word.text for word in words[start:end]))
    return ends_clause(current.text) and characters >= settings.clause_break_min_chars


def group_words(
    words: Sequence[WordTiming], settings: CueSettings, forced_breaks: Collection[int]
) -> list[tuple[int, int]]:
    groups: list[tuple[int, int]] = []
    start = 0
    while start < len(words):
        end = start + 1
        while end < len(words):
            if end in forced_breaks or breaks_after(words, start, end, settings):
                break
            if not span_fits(words[start : end + 1], settings):
                break
            end += 1
        groups.append((start, end))
        start = end
    return groups


def cue_bounds(
    words: Sequence[WordTiming], group: tuple[int, int], next_start: int | None, settings: CueSettings
) -> tuple[int, int]:
    start = words[group[0]].start_ms
    end = words[group[1] - 1].end_ms + settings.end_padding_ms
    if next_start is not None:
        end = min(end, next_start)
    minimum_end = start + settings.min_duration_ms
    if next_start is not None:
        minimum_end = min(minimum_end, next_start)
    end = max(end, minimum_end)
    return start, min(end, start + settings.max_duration_ms)


def build_cues(
    words: Sequence[WordTiming],
    *,
    settings: CueSettings | None = None,
    forced_breaks: Collection[int] = (),
) -> tuple[Cue, ...]:
    active = settings or CueSettings()
    spoken = [word for word in words if word.text.strip()]
    groups = group_words(spoken, active, forced_breaks)
    cues: list[Cue] = []
    for position, group in enumerate(groups):
        next_start = spoken[groups[position + 1][0]].start_ms if position + 1 < len(groups) else None
        start, end = cue_bounds(spoken, group, next_start, active)
        lines = layout_lines([word.text for word in spoken[group[0] : group[1]]], active.max_line_chars)
        if lines is None:
            raise ValueError("a cue group does not fit its lines")
        cues.append(Cue(position + 1, start, end, lines, group[0], group[1]))
    return tuple(cues)


def format_timestamp(milliseconds: int, decimal_separator: str) -> str:
    hours, remainder = divmod(milliseconds, MS_PER_HOUR)
    minutes, remainder = divmod(remainder, MS_PER_MINUTE)
    seconds, millis = divmod(remainder, MS_PER_SECOND)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{decimal_separator}{millis:03d}"


def escape_webvtt(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_webvtt(cues: Sequence[Cue]) -> str:
    blocks = ["WEBVTT\n"]
    for cue in cues:
        timing = f"{format_timestamp(cue.start_ms, '.')} --> {format_timestamp(cue.end_ms, '.')}"
        blocks.append(f"{cue.index}\n{timing}\n{escape_webvtt(cue.text)}\n")
    return "\n".join(blocks)


def render_srt(cues: Sequence[Cue]) -> str:
    blocks: list[str] = []
    for cue in cues:
        timing = f"{format_timestamp(cue.start_ms, ',')} --> {format_timestamp(cue.end_ms, ',')}"
        blocks.append(f"{cue.index}\n{timing}\n{cue.text}\n")
    return "\n".join(blocks)


def ass_timestamp(milliseconds: int, *, round_up: bool) -> str:
    centiseconds = -(-milliseconds // MS_PER_CENTISECOND) if round_up else milliseconds // MS_PER_CENTISECOND
    hours, remainder = divmod(centiseconds, MS_PER_HOUR // MS_PER_CENTISECOND)
    minutes, remainder = divmod(remainder, MS_PER_MINUTE // MS_PER_CENTISECOND)
    seconds, hundredths = divmod(remainder, MS_PER_SECOND // MS_PER_CENTISECOND)
    return f"{hours:d}:{minutes:02d}:{seconds:02d}.{hundredths:02d}"


def has_devanagari(text: str) -> bool:
    return any(DEVANAGARI_START <= ord(character) <= DEVANAGARI_END for character in text)


def escape_ass(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def ass_style(name: str, font: str, layout: CaptionLayout) -> str:
    return (
        f"Style: {name},{font},{layout.font_size},{TEXT_COLOUR},{TEXT_COLOUR},{BOX_COLOUR},{BOX_COLOUR},"
        f"0,0,0,0,100,100,0,0,3,{layout.box_padding},0,2,{layout.margin_h},{layout.margin_h},{layout.margin_v},1"
    )


def render_ass(
    cues: Sequence[Cue],
    aspect: Aspect,
    *,
    latin_font: str = "Geist",
    devanagari_font: str = "Noto Sans Devanagari",
) -> str:
    layout = CAPTION_LAYOUTS[aspect]
    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {layout.width}",
        f"PlayResY: {layout.height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic,"
        " Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL,"
        " MarginR, MarginV, Encoding",
        ass_style(LATIN_STYLE, latin_font, layout),
        ass_style(DEVANAGARI_STYLE, devanagari_font, layout),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    events = [
        f"Dialogue: 0,{ass_timestamp(cue.start_ms, round_up=False)},{ass_timestamp(cue.end_ms, round_up=True)},"
        f"{DEVANAGARI_STYLE if has_devanagari(cue.text) else LATIN_STYLE},,0,0,0,,"
        + "\\N".join(escape_ass(line) for line in cue.lines)
        for cue in cues
    ]
    return "\n".join([*header, *events]) + "\n"
