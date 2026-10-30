from pathlib import Path

import pytest

from evals.browser import engine_config, explicit_browser_environment
from motionile.core.config import get_settings
from motionile.engine.render.sandbox import browser_launch_environment

EVAL_VARIABLES = {
    "AI_ANTHROPIC_API_KEY": "anthropic-secret",
    "OPENAI_API_KEY": "openai-secret",
    "AI_LANGFUSE_PUBLIC_KEY": "langfuse-public",
    "AI_LANGFUSE_SECRET_KEY": "langfuse-secret",
    "AI_LANGFUSE_HOST": "https://langfuse.example.com",
    "EMBEDDING_MODEL": "text-embedding-3-small",
    "EMBEDDING_DIMENSIONS": "1536",
}
ALLOWED_NAMES = {"PATH", "HOME", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "LANG", "TZ"}


def test_the_browser_environment_never_carries_the_eval_variables(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name, value in EVAL_VARIABLES.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/home/app")
    get_settings.cache_clear()

    environment = browser_launch_environment(engine_config(tmp_path, explicit_browser_environment(get_settings())))

    assert set(environment) <= ALLOWED_NAMES
    assert not set(EVAL_VARIABLES) & set(environment)
    assert not set(EVAL_VARIABLES.values()) & {str(value) for value in environment.values()}
    assert environment["PATH"] == "/usr/bin"


def test_without_an_explicit_environment_the_browser_gets_only_the_fixed_locale(tmp_path: Path) -> None:
    config = engine_config(tmp_path, {})

    assert browser_launch_environment(config) == {"LANG": "C.UTF-8", "TZ": "UTC"}
