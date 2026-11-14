"""Exporta el contrato OpenAPI a ``backend/openapi.json``.

Uso::

    uv run python -m app.export_openapi           # regenera el fichero
    uv run python -m app.export_openapi --check   # falla si el fichero no está al día

El esquema no depende de los valores de configuración, así que si no hay entorno se usan
valores de relleno que solo sirven para construir la aplicación (no son credenciales).
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

OPENAPI_PATH = Path(__file__).resolve().parent.parent / "openapi.json"

_PLACEHOLDER_ENV = {
    "JWT_SECRET": "placeholder-only-for-openapi-export-0000",
    "DATABASE_URL": "sqlite://",
}


def build_schema() -> dict[str, Any]:
    for key, value in _PLACEHOLDER_ENV.items():
        os.environ.setdefault(key, value)
    from app.main import create_app

    return create_app().openapi()


def render(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Solo comprueba, no escribe")
    args = parser.parse_args(argv)

    content = render(build_schema())
    if args.check:
        current = OPENAPI_PATH.read_text(encoding="utf-8") if OPENAPI_PATH.exists() else ""
        if current != content:
            print(
                "openapi.json no está al día: ejecuta `uv run python -m app.export_openapi`",
                file=sys.stderr,
            )
            return 1
        print("openapi.json al día")
        return 0

    OPENAPI_PATH.write_text(content, encoding="utf-8")
    print(f"Escrito {OPENAPI_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
