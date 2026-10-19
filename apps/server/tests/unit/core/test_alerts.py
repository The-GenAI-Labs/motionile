import json

import pytest

from motionile.core.alerts import raise_alert
from motionile.core.config import AppEnv, AppSettings, Settings
from motionile.core.logging import REDACTED, configure_logging


def last_record(capfd: pytest.CaptureFixture[str]) -> dict[str, object]:
    record: dict[str, object] = json.loads(capfd.readouterr().out.strip().splitlines()[-1])
    return record


def test_alert_is_logged_at_critical_level_with_its_fields(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(app=AppSettings(env=AppEnv.CI)))

    raise_alert("credit_integrity_violation", user_ids=["u1", "u2"], expected=10, actual=7)

    record = last_record(capfd)
    assert record["level"] == "critical"
    assert record["alert"] is True
    assert record["alert_code"] == "credit_integrity_violation"
    assert record["user_ids"] == ["u1", "u2"]
    assert record["expected"] == 10
    assert record["actual"] == 7


def test_alert_fields_never_leak_secrets(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(app=AppSettings(env=AppEnv.CI)))

    raise_alert("webhook_failed", signature="sig_live", detail="signature mismatch")

    record = last_record(capfd)
    assert record["signature"] == REDACTED
    assert record["detail"] == "signature mismatch"
