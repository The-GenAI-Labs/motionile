from enum import StrEnum


class RunMode(StrEnum):
    DETERMINISTIC = "deterministic"
    CASSETTE = "cassette"
    LIVE = "live"
    AUTO = "auto"


class Selection(StrEnum):
    FULL = "full"
    CHANGED_AI = "changed_ai"


class PromptSourceKind(StrEnum):
    FILES = "files"
    DATABASE = "database"


CONCRETE_MODES = (RunMode.DETERMINISTIC, RunMode.CASSETTE, RunMode.LIVE)


def resolve_mode(requested: RunMode, *, has_provider_keys: bool) -> RunMode:
    if requested is not RunMode.AUTO:
        return requested
    return RunMode.LIVE if has_provider_keys else RunMode.CASSETTE
