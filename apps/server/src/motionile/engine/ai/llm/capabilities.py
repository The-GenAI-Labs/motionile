from collections.abc import Collection

CLAUDE_MARKER = "claude"
GPT_PREFIXES = ("gpt-", "o1", "o3", "o4", "text-embedding-")


def provider_of(model: str) -> str:
    prefix, separator, _ = model.partition("/")
    if separator:
        return prefix
    lowered = model.lower()
    if lowered.startswith(CLAUDE_MARKER):
        return "anthropic"
    if lowered.startswith(GPT_PREFIXES):
        return "openai"
    return "unknown"


def serves_claude(model: str) -> bool:
    return CLAUDE_MARKER in model.lower()


def uses_explicit_cache_control(model: str, providers: Collection[str]) -> bool:
    if provider_of(model) in providers:
        return True
    return serves_claude(model) and "anthropic" in providers


def uses_native_schema(model: str, providers: Collection[str], *, litellm_supports: bool) -> bool:
    return litellm_supports and provider_of(model) in providers
