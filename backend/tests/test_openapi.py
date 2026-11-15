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


def _walk(node: object) -> list[dict]:
    found = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found.extend(_walk(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_walk(value))
    return found


def test_openapi_exposes_phase_2_catalog() -> None:
    schema = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    paths = schema["paths"]
    assert set(paths["/datasets"]) == {"get", "post"}
    assert set(paths["/datasets/{slug}"]) == {"get"}
    assert set(paths["/datasets/{slug}/rdf"]) == {"get"}
    assert set(paths["/dataset/{slug}"]) == {"get"}
    assert set(paths["/dataset/{slug}/{version}"]) == {"get"}
    post = paths["/datasets"]["post"]
    assert set(post["requestBody"]["content"]) == {"text/turtle", "application/ld+json"}
    assert "422" in post["responses"]
    components = schema["components"]["schemas"]
    for name in ("DatasetCard", "DatasetPage", "DatasetDetail", "IngestErrorResponse"):
        assert name in components
    assert components["DomainRef"]["properties"]["slug"]["enum"] == ["it", "ot", "pqc", "ia"]
    # Esquemas tipados: ningún objeto genérico sin propiedades en los modelos del catálogo.
    catalog_models = [
        "DatasetCard",
        "DatasetDetail",
        "VersionDetail",
        "DcatMetadata",
        "DistributionRead",
        "ProvenanceStep",
        "IngestResult",
        "IngestErrorResponse",
    ]
    for name in catalog_models:
        for node in _walk(components[name]):
            if node.get("type") == "object":
                assert "properties" in node, name
    # Sin puntuaciones FAIR hasta la fase 4.
    assert "fair" not in json.dumps(components).lower()
