import json

import pytest
import structlog

from motionile.core.config import AppEnv, LogLevel, Settings
from motionile.core.logging import configure_logging


def test_emits_json_outside_local(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(app_env=AppEnv.CI))

    structlog.get_logger().info("job_started", job_id="abc")

    record = json.loads(capfd.readouterr().out.strip().splitlines()[-1])
    assert record["event"] == "job_started"
    assert record["job_id"] == "abc"
    assert record["level"] == "info"
    assert "timestamp" in record


def test_emits_readable_lines_locally(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(app_env=AppEnv.LOCAL))

    structlog.get_logger().info("server_ready", port=8000)

    output = capfd.readouterr().out
    assert "server_ready" in output
    assert "port" in output


def test_filters_below_configured_level(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(app_env=AppEnv.CI, log_level=LogLevel.WARNING))

    structlog.get_logger().info("hidden_event")

    assert "hidden_event" not in capfd.readouterr().out
