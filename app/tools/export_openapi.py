"""Write the OpenAPI schema to disk for the frontend's type generator.

The dashboard's request/response types are derived from this file rather than hand-written,
so a renamed field fails the frontend build instead of surfacing as `undefined` at runtime.

    uv run python -m app.tools.export_openapi
    pnpm --dir frontend --filter @rag/types generate

Reading it from a file rather than a running server means CI can regenerate types without
standing up Postgres and Redis first.
"""

import argparse
import json
from pathlib import Path

DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[2] / "frontend" / "packages" / "types" / "openapi.json"
)


def export(destination: Path) -> Path:
    # Imported lazily so `--help` does not pay for the application import graph.
    from app.main import create_app

    schema = create_app().openapi()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()

    written = export(arguments.output)
    print(f"wrote {written}")


if __name__ == "__main__":
    main()
