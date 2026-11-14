"""El contrato ``backend/openapi.json`` versionado está al día con el código."""

import json

from app.export_openapi import OPENAPI_PATH, build_schema, render


def test_openapi_json_is_up_to_date() -> None:
    hint = "ejecuta `uv run python -m app.export_openapi`"
    assert OPENAPI_PATH.exists(), f"Falta openapi.json: {hint}"
    assert OPENAPI_PATH.read_text(encoding="utf-8") == render(build_schema()), (
        f"openapi.json no está al día: {hint}"
    )


def test_openapi_exposes_phase_1_endpoints() -> None:
    schema = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    paths = schema["paths"]
    assert set(paths) >= {"/health", "/health/ready", "/auth/token", "/auth/me", "/users"}
    assert set(paths["/users"]) == {"get", "post"}
    assert set(paths["/users/{user_id}"]) == {"patch"}
    assert "OAuth2PasswordBearer" in schema["components"]["securitySchemes"]
    roles = schema["components"]["schemas"]["Role"]["enum"]
    assert roles == ["miembro", "editor", "admin"]
