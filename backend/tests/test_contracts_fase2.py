"""Coherencia de los contratos entre capas en la fase 2 (agente ``qa``).

- ``semantico`` -> ``backend``: las rutas de ``semantic/data`` que lee ``load-semantic`` y
  la copia de esos datos que usan las pruebas del backend.
- ``infra`` -> ``backend``: las variables de entorno de ``docker-compose.yml`` y de
  ``.env.example`` frente a las que lee ``app.config.Settings``.
- ``backend`` -> ``frontend``: los tipos de ``frontend/src/api/types.ts`` frente a los
  esquemas de ``backend/openapi.json``.

Cada prueba se salta si la carpeta de la otra capa no está (p. ej. dentro de la imagen
Docker del backend, que solo contiene ``backend/``).
"""

import filecmp
import json
import re
from pathlib import Path

import pytest

from app import ingest
from app.config import Settings
from app.export_openapi import OPENAPI_PATH
from tests.conftest import FIXTURE_DATA_DIR, FIXTURE_SEMANTIC_DIR, REPO_SEMANTIC_DIR

REPO_ROOT = REPO_SEMANTIC_DIR.parent
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
FRONTEND_TYPES = REPO_ROOT / "frontend" / "src" / "api" / "types.ts"


def _require(path: Path) -> Path:
    if not path.exists():
        pytest.skip(f"no existe {path.relative_to(REPO_ROOT)} en este entorno")
    return path


# --- semantico -> backend --------------------------------------------------------------


def test_load_semantic_paths_exist_in_semantic_dir() -> None:
    root = _require(REPO_SEMANTIC_DIR / "data").parent
    assert (root / ingest.VOCAB_FILE).is_file()
    assert (root / ingest.CATALOG_FILE).is_file()
    assert (root / ingest.SHAPES_DIR).is_dir() and list((root / ingest.SHAPES_DIR).glob("*.ttl"))
    series = sorted(path.stem for path in (root / ingest.SYNTHETIC_DIR).glob("*.ttl"))
    assert series == [
        "ejemplos-adversarios-vision",
        "hallazgos-auditorias-intrusion",
        "modbus-tcp-testbed",
    ]


def test_backend_fixture_data_is_an_exact_copy_of_semantic_data() -> None:
    """``backend/tests/fixtures/data`` es una copia de ``semantic/data``: si los datos de
    ``semantico`` cambian, las pruebas del backend deben usar los mismos."""
    source = _require(REPO_SEMANTIC_DIR / "data")

    def files(root: Path) -> list[str]:
        return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())

    assert files(FIXTURE_DATA_DIR) == files(source)
    _match, mismatch, errors = filecmp.cmpfiles(
        source, FIXTURE_DATA_DIR, files(source), shallow=False
    )
    assert (mismatch, errors) == ([], [])


@pytest.mark.parametrize(
    "relative",
    ["vocabularios", "ontologias", "shapes/ontologias-vocabularios.ttl"],
)
def test_backend_fixture_vocabularies_are_an_exact_copy_of_semantic(relative: str) -> None:
    """Fase 3: ``backend/tests/fixtures/semantic`` copia vocabularios, ontologías y la forma
    de ontologías y vocabularios de ``semantic/``."""
    source = _require(REPO_SEMANTIC_DIR / relative)
    copy = FIXTURE_SEMANTIC_DIR / relative
    if source.is_file():
        assert filecmp.cmp(source, copy, shallow=False)
        return

    def files(root: Path) -> list[str]:
        return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())

    assert files(copy) == files(source)
    _match, mismatch, errors = filecmp.cmpfiles(source, copy, files(source), shallow=False)
    assert (mismatch, errors) == ([], [])


# --- infra -> backend ------------------------------------------------------------------


def _settings_env_names() -> set[str]:
    return {name.upper() for name in Settings.model_fields}


def _compose_backend_environment() -> set[str]:
    """Nombres de las variables del bloque ``environment`` del servicio ``backend``."""
    lines = _require(COMPOSE_FILE).read_text(encoding="utf-8").splitlines()
    names: set[str] = set()
    in_backend = in_environment = False
    for line in lines:
        if re.fullmatch(r"  [a-z0-9_-]+:\s*", line):
            in_backend, in_environment = line.strip() == "backend:", False
            continue
        if not in_backend:
            continue
        if re.fullmatch(r"    [a-z_]+:.*", line):
            in_environment = line.strip() == "environment:"
            continue
        match = re.fullmatch(r"      ([A-Z][A-Z0-9_]*):.*", line)
        if in_environment and match:
            names.add(match.group(1))
    return names


def _env_example() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in _require(ENV_EXAMPLE).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def test_compose_passes_the_phase_2_variables_the_backend_reads() -> None:
    environment = _compose_backend_environment()
    assert {"SEMANTIC_DIR", "FUSEKI_USER", "FUSEKI_PASSWORD"} <= environment
    # Compose no define para el backend ninguna variable que el backend no lea.
    assert environment <= _settings_env_names(), environment - _settings_env_names()


def test_env_example_matches_backend_settings() -> None:
    example = _env_example()
    # Variables de otros servicios (PostgreSQL, Fuseki, frontend) y puertos del host.
    not_backend = {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "FUSEKI_ADMIN_PASSWORD"}
    backend_keys = {
        key
        for key in example
        if key not in not_backend and not key.startswith("VITE_") and not key.endswith("_HOST_PORT")
    }
    unknown = backend_keys - _settings_env_names()
    assert unknown == set(), f".env.example documenta variables que el backend no lee: {unknown}"
    # Las obligatorias (sin valor por defecto) están documentadas.
    required = {
        name.upper() for name, field in Settings.model_fields.items() if field.is_required()
    }
    assert required <= set(example), required - set(example)
    # Los secretos del backend no tienen un valor utilizable en el ejemplo.
    assert example["JWT_SECRET"] == ""
    assert "FUSEKI_PASSWORD" not in example
    # Las variables nuevas de la fase 2.
    assert {"FUSEKI_USER", "SEMANTIC_DIR", "FRONTEND_BASE_URL"} <= set(example)
    assert example["VITE_BASE_URI"] == example["BASE_URI"]


# --- backend -> frontend ---------------------------------------------------------------

# Interfaz de TypeScript -> esquema de OpenAPI, cuando no se llaman igual.
TYPE_NAMES = {"TokenResponse": "Token", "CurrentUser": "UserRead", "HealthResponse": "HealthStatus"}


def _typescript_interfaces() -> dict[str, dict[str, bool]]:
    """``{interfaz: {propiedad: admite_null}}`` de ``frontend/src/api/types.ts``."""
    text = _require(FRONTEND_TYPES).read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    interfaces: dict[str, dict[str, bool]] = {}
    for name, body in re.findall(r"export interface (\w+) \{(.*?)\n\}", text, flags=re.DOTALL):
        properties: dict[str, bool] = {}
        for prop, optional, ts_type in re.findall(
            r"^\s*(\w+)(\??):\s*([^\n]+)$", body, re.MULTILINE
        ):
            assert optional == "", f"{name}.{prop}: el contrato no tiene propiedades opcionales"
            properties[prop] = bool(re.search(r"\|\s*null\b", ts_type))
        interfaces[name] = properties
    return interfaces


def _nullable(schema: dict) -> bool:
    return any(option.get("type") == "null" for option in schema.get("anyOf", []))


def test_frontend_types_match_the_openapi_contract() -> None:
    interfaces = _typescript_interfaces()
    schemas = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))["components"]["schemas"]
    assert {"DatasetCard", "DatasetPage", "DatasetDetail", "VersionDetail"} <= set(interfaces)
    for ts_name, properties in interfaces.items():
        schema_name = TYPE_NAMES.get(ts_name, ts_name)
        assert schema_name in schemas, f"{ts_name}: no hay esquema {schema_name} en openapi.json"
        schema = schemas[schema_name]
        assert set(properties) == set(schema["properties"]), ts_name
        # El frontend trata todos los campos como siempre presentes: el contrato debe
        # exigirlos, salvo los que declaran un valor por defecto (siempre se devuelven).
        with_default = {p for p, s in schema["properties"].items() if "default" in s}
        assert set(schema.get("required", [])) | with_default == set(properties), ts_name
        for prop, nullable in properties.items():
            assert nullable == _nullable(schema["properties"][prop]), f"{ts_name}.{prop}"


def test_frontend_enums_match_the_openapi_contract() -> None:
    text = _require(FRONTEND_TYPES).read_text(encoding="utf-8")
    contract = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))

    def ts_union(name: str) -> list[str]:
        match = re.search(rf"export type {name} = ([^\n]+)", text)
        assert match, name
        return re.findall(r"'([^']+)'", match.group(1))

    def query_enum(path: str, parameter: str) -> list[str]:
        for item in contract["paths"][path]["get"]["parameters"]:
            if item["name"] == parameter:
                (values,) = [o["enum"] for o in item["schema"]["anyOf"] if "enum" in o]
                return values
        raise AssertionError(parameter)

    assert ts_union("DomainSlug") == query_enum("/datasets", "domain")
    assert (
        ts_union("DomainSlug")
        == contract["components"]["schemas"]["DomainRef"]["properties"]["slug"]["enum"]
    )
    assert ts_union("RdfFormat") == query_enum("/datasets/{slug}/rdf", "format")
    assert ts_union("Role") == contract["components"]["schemas"]["Role"]["enum"]
