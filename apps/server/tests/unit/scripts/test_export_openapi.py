import json
from pathlib import Path

from motionile.scripts.export_openapi import main, render_openapi


def test_rendering_is_deterministic() -> None:
    assert render_openapi() == render_openapi()


def test_schema_documents_health_routes() -> None:
    schema = json.loads(render_openapi())

    assert set(schema["paths"]) >= {"/health/live", "/health/ready"}
    assert schema["info"]["title"] == "Motionile API"


def test_output_has_sorted_keys_and_trailing_newline(tmp_path: Path) -> None:
    output = tmp_path / "openapi.json"

    main(["--output", str(output)])

    content = output.read_text(encoding="utf-8")
    assert content.endswith("}\n")
    assert content == json.dumps(json.loads(content), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
