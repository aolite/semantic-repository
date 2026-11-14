"""Ingesta ``POST /datasets``: permisos, validación SHACL, URIs, sustitución y auditoría."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, URIRef
from rdflib.compare import isomorphic
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import AuditAction, AuditEvent, Role, User
from app.triplestore import MemoryStore
from app.uris import Uris
from tests.conftest import BASE_URI, REPO_SEMANTIC_DIR

TURTLE = {"Content-Type": "text/turtle"}
JSONLD = {"Content-Type": "application/ld+json"}
SERIES = f"{BASE_URI}dataset/modbus-tcp-testbed"


def _modbus(semantic_dir: Path) -> bytes:
    return (semantic_dir / "data" / "sintetico" / "modbus-tcp-testbed.ttl").read_bytes()


def _editor(make_user: Callable[..., User], login: Callable[..., dict[str, str]], role: Role):
    make_user("pub", role)
    return login("pub")


MINIMAL = """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct:  <http://purl.org/dc/terms/> .
<dataset/prueba> a dcat:DatasetSeries ;
    dct:title "Serie de prueba"@es ; dct:description "Descripción"@es ;
    dcat:last <dataset/prueba/1.0.0> .
<dataset/prueba/1.0.0> a dcat:Dataset ;
    dct:title "Serie de prueba"@es ; dct:description "Descripción"@es ;
    dcat:version "1.0.0" ; dcat:inSeries <dataset/prueba> ;
    dct:accessRights <http://publications.europa.eu/resource/authority/access-right/PUBLIC> ;
    dcat:distribution <dataset/prueba/1.0.0/csv> .
<dataset/prueba/1.0.0/csv> a dcat:Distribution ;
    dcat:accessURL <dataset/prueba/1.0.0/csv> .
"""


# --- Permisos -----------------------------------------------------------------------


@pytest.mark.parametrize(("role", "expected"), [(Role.EDITOR, 201), (Role.ADMIN, 201)])
def test_editor_and_admin_can_publish(
    client: TestClient,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
    semantic_dir: Path,
    store: MemoryStore,
    role: Role,
    expected: int,
) -> None:
    headers = _editor(make_user, login, role) | TURTLE
    response = client.post("/datasets", content=_modbus(semantic_dir), headers=headers)
    assert response.status_code == expected, response.text
    body = response.json()
    assert body == {
        "slug": "modbus-tcp-testbed",
        "uri": SERIES,
        "graph": SERIES,
        "versions": ["1.0.0", "2.0.0", "2.1.0"],
        "triples": body["triples"],
        "created": True,
        "changed": True,
    }
    assert SERIES in store.graph_names()


def test_member_cannot_publish(
    client: TestClient,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
    semantic_dir: Path,
    store: MemoryStore,
) -> None:
    headers = _editor(make_user, login, Role.MIEMBRO) | TURTLE
    response = client.post("/datasets", content=_modbus(semantic_dir), headers=headers)
    assert response.status_code == 403
    assert store.graph_names() == set()


def test_anonymous_cannot_publish(
    client: TestClient, semantic_dir: Path, store: MemoryStore
) -> None:
    response = client.post("/datasets", content=_modbus(semantic_dir), headers=TURTLE)
    assert response.status_code == 401
    assert store.graph_names() == set()


# --- Ingesta válida, sustitución e idempotencia --------------------------------------


@pytest.fixture
def editor_headers(
    make_user: Callable[..., User], login: Callable[..., dict[str, str]]
) -> dict[str, str]:
    return _editor(make_user, login, Role.EDITOR)


def test_publish_stores_graph_with_base_uri(
    client: TestClient, editor_headers: dict[str, str], semantic_dir: Path, store: MemoryStore
) -> None:
    client.post("/datasets", content=_modbus(semantic_dir), headers=editor_headers | TURTLE)
    stored = store.get_graph(SERIES)
    expected = Graph().parse(
        semantic_dir / "data" / "sintetico" / "modbus-tcp-testbed.ttl",
        format="turtle",
        publicID=BASE_URI,
    )
    assert isomorphic(stored, expected)


def test_republish_same_content_is_idempotent(
    client: TestClient, editor_headers: dict[str, str], semantic_dir: Path
) -> None:
    first = client.post("/datasets", content=_modbus(semantic_dir), headers=editor_headers | TURTLE)
    second = client.post(
        "/datasets", content=_modbus(semantic_dir), headers=editor_headers | TURTLE
    )
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["changed"] is False


def test_republish_replaces_the_whole_graph(
    client: TestClient, editor_headers: dict[str, str], store: MemoryStore
) -> None:
    client.post("/datasets", content=MINIMAL.encode(), headers=editor_headers | TURTLE)
    changed = MINIMAL.replace('"Serie de prueba"@es', '"Nuevo"@es', 1)  # título de la serie
    response = client.post("/datasets", content=changed.encode(), headers=editor_headers | TURTLE)
    assert response.status_code == 200
    assert response.json()["changed"] is True
    graph = store.get_graph(f"{BASE_URI}dataset/prueba")
    titles = {str(o) for o in graph.objects(URIRef(f"{BASE_URI}dataset/prueba"), None)}
    assert "Nuevo" in titles and "Serie de prueba" not in titles


def test_publish_json_ld(
    client: TestClient, editor_headers: dict[str, str], semantic_dir: Path, store: MemoryStore
) -> None:
    graph = Graph().parse(data=MINIMAL, format="turtle", publicID=BASE_URI)
    body = graph.serialize(format="json-ld")
    response = client.post("/datasets", content=body.encode(), headers=editor_headers | JSONLD)
    assert response.status_code == 201, response.text
    assert isomorphic(store.get_graph(f"{BASE_URI}dataset/prueba"), graph)


def test_publish_is_audited(
    client: TestClient,
    editor_headers: dict[str, str],
    semantic_dir: Path,
    session_factory: sessionmaker[Session],
) -> None:
    client.post("/datasets", content=_modbus(semantic_dir), headers=editor_headers | TURTLE)
    with session_factory() as session:
        event = session.scalars(
            select(AuditEvent).where(AuditEvent.action == AuditAction.DATASET_PUBLISHED)
        ).one()
    assert event.actor_username == "pub"
    assert event.actor_id is not None
    assert event.details["series"] == SERIES
    assert event.details["slug"] == "modbus-tcp-testbed"
    assert event.details["versions"] == ["1.0.0", "2.0.0", "2.1.0"]
    assert event.details["via"] == "api"


# --- Ingesta no válida (422) ---------------------------------------------------------


def _post(client: TestClient, headers: dict[str, str], body: str | bytes, ctype=TURTLE):
    content = body.encode() if isinstance(body, str) else body
    return client.post("/datasets", content=content, headers=headers | ctype)


INVALID_EXAMPLES = sorted((REPO_SEMANTIC_DIR / "examples" / "invalid").glob("*.ttl"))


@pytest.mark.parametrize("path", INVALID_EXAMPLES, ids=lambda p: p.stem)
def test_invalid_examples_are_rejected(
    client: TestClient, editor_headers: dict[str, str], store: MemoryStore, path: Path
) -> None:
    response = _post(client, editor_headers, path.read_bytes())
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["kind"] in {"shacl", "uri", "structure"}
    assert body["issues"]
    assert store.graph_names() == set()


def test_shacl_report_is_readable(
    client: TestClient, editor_headers: dict[str, str], store: MemoryStore
) -> None:
    version_block = '<dataset/prueba/1.0.0> a dcat:Dataset ;\n    dct:title "Serie de prueba"@es ;'
    assert version_block in MINIMAL
    without_title = MINIMAL.replace(version_block, "<dataset/prueba/1.0.0> a dcat:Dataset ;")
    response = _post(client, editor_headers, without_title)
    assert response.status_code == 422
    data = response.json()
    assert data["kind"] == "shacl"
    assert data["report"] and "Validation Report" in data["report"]
    issue = data["issues"][0]
    assert issue["focus_node"] == f"{BASE_URI}dataset/prueba/1.0.0"
    assert issue["path"] == "http://purl.org/dc/terms/title"
    assert issue["source_shape"] == f"{BASE_URI}shapes#Dataset-title"
    assert "dct:title" in issue["message"]
    assert store.graph_names() == set()


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ("esto no es turtle <", "RDF no válido"),
        ("", "vacío"),
        ("@prefix dct: <http://purl.org/dc/terms/> .", "vacío"),
    ],
)
def test_syntax_errors(
    client: TestClient, editor_headers: dict[str, str], body: str, fragment: str
) -> None:
    response = _post(client, editor_headers, body)
    assert response.status_code == 422
    assert response.json()["kind"] == "syntax"
    assert fragment in response.json()["detail"]


def test_non_utf8_is_rejected(client: TestClient, editor_headers: dict[str, str]) -> None:
    response = _post(client, editor_headers, "título".encode("latin-1"))
    assert response.status_code == 422
    assert response.json()["kind"] == "syntax"


@pytest.mark.parametrize(
    "context",
    [
        "https://example.org/context.jsonld",
        ["https://example.org/context.jsonld"],
        {"@import": "https://example.org/context.jsonld"},
        {"dct": "http://purl.org/dc/terms/", "x": {"@context": "https://example.org/c"}},
    ],
)
def test_json_ld_remote_contexts_are_rejected(
    client: TestClient, editor_headers: dict[str, str], context: object
) -> None:
    document = {"@context": context, "@id": f"{BASE_URI}dataset/prueba"}
    response = _post(client, editor_headers, json.dumps(document), JSONLD)
    assert response.status_code == 422
    assert "contextos remotos" in response.json()["detail"]


def test_two_series_are_rejected(client: TestClient, editor_headers: dict[str, str]) -> None:
    other = MINIMAL.replace("prueba", "otra")
    response = _post(client, editor_headers, MINIMAL + other)
    assert response.status_code == 422
    assert response.json()["kind"] == "structure"


def test_no_series_is_rejected(client: TestClient, editor_headers: dict[str, str]) -> None:
    response = _post(client, editor_headers, MINIMAL.replace("a dcat:DatasetSeries", "a dcat:X"))
    assert response.status_code == 422
    assert response.json()["kind"] == "structure"


@pytest.mark.parametrize(
    ("old", "new", "focus"),
    [
        # Serie fuera de BASE_URI
        ("<dataset/prueba>", "<https://otro.example/dataset/prueba>", None),
        # Slug no válido
        ("<dataset/prueba>", "<dataset/Prueba_Mala>", None),
        # Versión con URI que no es {serie}/{version}
        ("<dataset/prueba/1.0.0>", "<dataset/prueba/v1>", f"{BASE_URI}dataset/prueba/v1"),
        # Distribución que no cuelga de su versión
        ("<dataset/prueba/1.0.0/csv>", "<dataset/otra/1.0.0/csv>", None),
    ],
)
def test_uri_pattern_violations(
    client: TestClient,
    editor_headers: dict[str, str],
    store: MemoryStore,
    old: str,
    new: str,
    focus: str | None,
) -> None:
    response = _post(client, editor_headers, MINIMAL.replace(old, new))
    assert response.status_code == 422, response.text
    assert response.json()["kind"] == "uri"
    if focus:
        assert focus in {i["focus_node"] for i in response.json()["issues"]}
    assert store.graph_names() == set()


def test_version_number_must_match_uri(client: TestClient, editor_headers: dict[str, str]) -> None:
    response = _post(client, editor_headers, MINIMAL.replace('"1.0.0"', '"1.0.1"'))
    assert response.status_code == 422
    assert "dcat:version" in response.json()["issues"][0]["message"]


@pytest.mark.parametrize(
    "extra",
    [
        # Reescribir otra serie
        '<dataset/modbus-tcp-testbed> <http://purl.org/dc/terms/title> "Secuestrada" .',
        # Reescribir el vocabulario
        '<vocab/ot/modbus-tcp> <http://www.w3.org/2004/02/skos/core#prefLabel> "X"@es .',
        # Recursos ajenos a BASE_URI
        '<https://otro.example/x> <http://purl.org/dc/terms/title> "X" .',
    ],
)
def test_cannot_describe_foreign_resources(
    client: TestClient, editor_headers: dict[str, str], store: MemoryStore, extra: str
) -> None:
    response = _post(client, editor_headers, MINIMAL + extra)
    assert response.status_code == 422
    assert response.json()["kind"] == "uri"
    assert store.graph_names() == set()


def test_unsupported_media_type(client: TestClient, editor_headers: dict[str, str]) -> None:
    response = client.post(
        "/datasets",
        content=MINIMAL.encode(),
        headers=editor_headers | {"Content-Type": "text/plain"},
    )
    assert response.status_code == 415


def test_body_too_large(
    client: TestClient,
    editor_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client.app.dependency_overrides  # noqa: B018 - el cliente ya está creado
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "ingest_max_bytes", 100)
    response = _post(client, editor_headers, MINIMAL)
    assert response.status_code == 413


def test_missing_fuseki_credentials_gives_clear_503(
    client: TestClient, editor_headers: dict[str, str], uris: Uris
) -> None:
    import httpx

    from app.config import get_settings
    from app.deps import get_triplestore
    from app.triplestore import FusekiStore

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="", headers={"Content-Type": "application/n-triples"})

    fuseki = FusekiStore(
        "http://fuseki.test:3030",
        "itot",
        credentials=None,
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    assert get_settings().fuseki_write_credentials is None
    client.app.dependency_overrides[get_triplestore] = lambda: fuseki
    response = _post(client, editor_headers, MINIMAL)
    assert response.status_code == 503
    assert "FUSEKI_USER" in response.json()["detail"]
    assert "FUSEKI_PASSWORD" in response.json()["detail"]
