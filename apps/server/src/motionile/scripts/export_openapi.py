import argparse
import json
from pathlib import Path
from typing import Any

from motionile.entrypoints.api import create_app

DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "openapi.json"


def render_openapi() -> str:
    schema: dict[str, Any] = create_app(include_test_routes=False).openapi()
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def export_openapi(output: Path) -> None:
    output.write_text(render_openapi(), encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Write the API OpenAPI schema to a file.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args(argv)
    export_openapi(arguments.output)


if __name__ == "__main__":
    main()
