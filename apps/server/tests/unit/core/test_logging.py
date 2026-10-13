import json

import pytest
import structlog

from motionile.core.config import AppEnv, AppSettings, LoggingSettings, LogLevel, Settings
from motionile.core.logging import (
    REDACTED,
    bind_request_context,
    clear_request_context,
    configure_logging,
    is_sensitive_key,
    redact,
)


def settings_for(env: AppEnv, level: LogLevel = LogLevel.INFO) -> Settings:
    return Settings(app=AppSettings(env=env), logging=LoggingSettings(level=level))


def test_emits_json_outside_local(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging(settings_for(AppEnv.CI))

    structlog.get_logger().info("job_started", job_id="abc")

    record = json.loads(capfd.readouterr().out.strip().splitlines()[-1])
    assert record["event"] == "job_started"
    assert record["job_id"] == "abc"
    assert record["level"] == "info"
    assert "timestamp" in record


def test_emits_readable_lines_locally(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging(settings_for(AppEnv.LOCAL))

    structlog.get_logger().info("server_ready", port=8000)

    assert "server_ready" in capfd.readouterr().out


def test_filters_below_configured_level(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging(settings_for(AppEnv.CI, LogLevel.WARNING))

    structlog.get_logger().info("hidden_event")

    assert "hidden_event" not in capfd.readouterr().out


def test_redacts_sensitive_fields_in_output(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging(settings_for(AppEnv.CI))

    structlog.get_logger().info(
        "login",
        password="hunter2",  # noqa: S106
        headers={"Authorization": "Bearer abc", "Accept": "json"},
        otp_code="123456",
    )

    output = capfd.readouterr().out
    assert "hunter2" not in output
    assert "Bearer abc" not in output
    assert "123456" not in output
    assert "json" in output


def test_request_context_is_bound_and_cleared(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging(settings_for(AppEnv.CI))
    bind_request_context(request_id="req-1", route="/v1/things")

    structlog.get_logger().info("inside")
    clear_request_context()
    structlog.get_logger().info("outside")

    lines = [json.loads(line) for line in capfd.readouterr().out.strip().splitlines()]
    assert lines[-2]["request_id"] == "req-1"
    assert "request_id" not in lines[-1]


@pytest.mark.parametrize(
    "key",
    [
        "Authorization",
        "cookie",
        "Set-Cookie",
        "password",
        "new_password",
        "refresh_token",
        "client_secret",
        "otp",
        "X-CSRF-Token",
        "api_key",
        "aws_access_key_id",
    ],
)
def test_sensitive_keys(key: str) -> None:
    assert is_sensitive_key(key)


@pytest.mark.parametrize("key", ["code", "status", "user_id", "path", "error_code"])
def test_ordinary_keys(key: str) -> None:
    assert not is_sensitive_key(key)


def test_redact_walks_nested_structures() -> None:
    value = {"outer": [{"token": "t", "safe": 1}], "password": "p"}

    assert redact(value) == {"outer": [{"token": REDACTED, "safe": 1}], "password": REDACTED}
    assert redact("plain") == "plain"
