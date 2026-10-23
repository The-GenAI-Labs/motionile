import json
from typing import Any

from motionile.engine.render.models import ValidationReport


def report_payload(report: ValidationReport) -> dict[str, Any]:
    return report.model_dump(mode="json", by_alias=True)


def report_bytes(report: ValidationReport) -> bytes:
    return json.dumps(report_payload(report), separators=(",", ":")).encode("utf-8")


def report_from_payload(payload: dict[str, Any]) -> ValidationReport:
    cleaned = {name: value for name, value in payload.items() if name != "valid"}
    return ValidationReport.model_validate(cleaned)


def report_from_bytes(raw: bytes) -> ValidationReport:
    return report_from_payload(json.loads(raw))
