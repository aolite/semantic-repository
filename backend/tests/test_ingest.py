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
from app.uris import DCAT, Uris
from tests.conftest import (
    BASE_URI,
    REPO_SEMANTIC_DIR,
    fake_fuseki_read,
    user_graphs,
    without_membership,
)

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
<catalogo/pruebas> dcat:dataset <dataset/prueba> .
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
    assert SERIES in user_graphs(store)


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
    assert user_graphs(store) == set()


def test_anonymous_cannot_publish(
    client: TestClient, semantic_dir: Path, store: MemoryStore
) -> None:
    response = client.post("/datasets", content=_modbus(semantic_dir), headers=TURTLE)
    assert response.status_code == 401
    assert user_graphs(store) == set()


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
    # El triple de pertenencia (decisión 49) va al grafo del catálogo, no al de la serie.
    assert isomorphic(stored, without_membership(expected))
    catalog = store.get_graph(f"{BASE_URI}catalogo/sintetico")
    assert (URIRef(f"{BASE_URI}catalogo/sintetico"), DCAT.dataset, URIRef(SERIES)) in catalog


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
    assert isomorphic(store.get_graph(f"{BASE_URI}dataset/prueba"), without_membership(graph))


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
    assert user_graphs(store) == set()


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
    assert user_graphs(store) == set()


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
    assert user_graphs(store) == set()


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
    assert user_graphs(store) == set()


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
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "ingest_max_bytes", 100)
    response = _post(client, editor_headers, MINIMAL)
    assert response.status_code == 413


# --- QA-G2-03: autenticación antes que el cuerpo ---------------------------------------


def test_authentication_is_checked_before_reading_the_body(
    client: TestClient,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "ingest_max_bytes", 100)
    wrong_type = {"Content-Type": "text/plain"}
    big = b"#" * 1000
    # Anónimo: 401 aunque el tipo sea incorrecto o el cuerpo demasiado grande.
    assert client.post("/datasets", content=MINIMAL.encode(), headers=wrong_type).status_code == (
        401
    )
    assert client.post("/datasets", content=big, headers=TURTLE).status_code == 401
    # Miembro: 403 en los mismos casos.
    make_user("socio", Role.MIEMBRO)
    member = login("socio")
    assert (
        client.post("/datasets", content=MINIMAL.encode(), headers=member | wrong_type).status_code
        == 403
    )
    assert client.post("/datasets", content=big, headers=member | TURTLE).status_code == 403


def test_body_is_not_read_without_authentication(client: TestClient) -> None:
    """El cuerpo se envía en trozos: sin autenticar no se consume ninguno."""
    consumed: list[bytes] = []

    def body():
        for _ in range(3):
            consumed.append(b"x")
            yield MINIMAL.encode()

    response = client.post("/datasets", content=body(), headers=TURTLE)
    assert response.status_code == 401
    # El cliente de pruebas puede haber preparado el primer trozo, pero el servidor no
    # ha pedido el resto.
    assert len(consumed) <= 1


# --- QA-G2-01: IRIs no válidas ----------------------------------------------------------

BAD_IRIS = [
    "<http://x.example/a b>",
    "<http://x.example/{}|^`>",
    "<http://x.example/a\\u000Ab>",
    "<http://x.example/a\\u0009b>",
    "<http://x.example/a\\u0000b>",
    "<http://x.example/a\\u003Cb>",
    "<http://x.example/a\\u003Eb>",
    "<http://x.example/a\\u0022b>",
    "<http://x.example/a\\u005Cb>",
]


@pytest.mark.parametrize("bad", BAD_IRIS)
@pytest.mark.parametrize("position", ["object", "predicate", "datatype"])
def test_invalid_iris_are_rejected_before_writing(
    client: TestClient,
    editor_headers: dict[str, str],
    store: MemoryStore,
    bad: str,
    position: str,
) -> None:
    triple = {
        "object": f"<dataset/prueba> dct:relation {bad} .",
        "predicate": f'<dataset/prueba> {bad} "x" .',
        "datatype": f'<dataset/prueba> dct:relation "x"^^{bad} .',
    }[position]
    response = _post(client, editor_headers, MINIMAL + triple + "\n")
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["kind"] == "uri"
    assert body["report"] is None  # antes de SHACL
    assert body["issues"][0]["message"].startswith("IRI no válida")
    assert user_graphs(store) == set()


def test_invalid_subject_iri_is_rejected(
    client: TestClient, editor_headers: dict[str, str], store: MemoryStore
) -> None:
    body = MINIMAL.replace("<dataset/prueba/1.0.0/csv>", "<dataset/prueba/1.0.0/c\\u0020sv>")
    response = _post(client, editor_headers, body)
    assert response.status_code == 422
    assert response.json()["kind"] == "uri"
    assert user_graphs(store) == set()


def test_invalid_iri_in_json_ld_never_reaches_the_store(
    client: TestClient, editor_headers: dict[str, str], store: MemoryStore
) -> None:
    """El analizador JSON-LD de rdflib descarta él mismo los triples con IRIs no válidas
    en ``@id``; si alguno pasara, lo pararía ``check_terms``. En ningún caso se guarda."""
    graph = Graph().parse(data=MINIMAL, format="turtle", publicID=BASE_URI)
    document = json.loads(graph.serialize(format="json-ld"))
    document.append(
        {
            "@id": f"{BASE_URI}dataset/prueba",
            "http://purl.org/dc/terms/relation": {"@id": "http://x.example/a b\nc"},
        }
    )
    response = _post(client, editor_headers, json.dumps(document), JSONLD)
    assert response.status_code in (201, 422), response.text
    for name in user_graphs(store):
        for triple in store.get_graph(name):
            assert not any(isinstance(term, URIRef) and " " in term for term in triple)
    if response.status_code == 201:
        read = client.get("/dataset/prueba", headers={"Accept": "text/turtle"})
        assert read.status_code == 200


def test_nothing_malformed_reaches_fuseki(
    client: TestClient, editor_headers: dict[str, str]
) -> None:
    import httpx

    from app.deps import get_triplestore
    from app.triplestore import FusekiStore

    puts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            puts.append(request)
            return httpx.Response(201)
        # El catálogo de la serie existe (decisión 49); el resto de grafos, vacíos.
        text = fake_fuseki_read(request)
        return httpx.Response(200, text=text, headers={"Content-Type": "application/n-triples"})

    client.app.dependency_overrides[get_triplestore] = lambda: FusekiStore(
        "http://fuseki.test:3030",
        "itot",
        credentials=("backend", "clave-ficticia"),
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    bad = MINIMAL + "<dataset/prueba> dct:relation <http://x.example/a\\u000Ab> .\n"
    assert _post(client, editor_headers, bad).status_code == 422
    assert puts == []
    assert _post(client, editor_headers, MINIMAL).status_code == 201
    assert puts  # la serie y el triple de pertenencia en el grafo del catálogo
    for line in puts[0].content.decode().splitlines():
        assert line.endswith(" ."), line


# --- QA-G2-02: anidamiento ---------------------------------------------------------------


@pytest.mark.parametrize(
    "document",
    [
        "[" * 100_000 + "]" * 100_000,
        '{"a":' * 100_000 + "1" + "}" * 100_000,
        "[" * 65 + "]" * 65,  # justo por encima del límite, sin llegar a la recursión
        '{"@context":{"p":"http://x.example/p"},"@id":"'
        + f"{BASE_URI}dataset/prueba"
        + '","p":'
        + '{"p":' * 5000
        + "1"
        + "}" * 5000
        + "}",
    ],
    ids=["listas", "objetos", "limite", "nodos-anidados"],
)
def test_deeply_nested_json_ld_is_a_422(
    client: TestClient, editor_headers: dict[str, str], store: MemoryStore, document: str
) -> None:
    response = _post(client, editor_headers, document, JSONLD)
    assert response.status_code == 422, response.text
    assert response.json()["kind"] == "syntax"
    assert "anidamiento" in response.json()["detail"]
    assert user_graphs(store) == set()


def test_json_depth_limit_is_exactly_64() -> None:
    from app.ingest import MAX_NESTING_DEPTH, _json_depth_exceeds

    assert MAX_NESTING_DEPTH == 64
    assert not _json_depth_exceeds(json.loads("[" * 64 + "]" * 64), 64)
    assert _json_depth_exceeds(json.loads("[" * 65 + "]" * 65), 64)
    assert not _json_depth_exceeds({"a": [1, {"b": "c"}]}, 64)
    assert not _json_depth_exceeds("texto", 64)


@pytest.mark.parametrize(
    "tail",
    [
        "<dataset/prueba> dct:relation " + "[ dct:relation " * 20_000 + "1" + " ]" * 20_000 + " .",
        "<dataset/prueba> dct:relation " + "(" * 20_000 + ")" * 20_000 + " .",
        # Por debajo de la recursión del analizador, pero por encima del límite: se
        # rechaza para que el RDF devuelto se pueda serializar siempre.
        "<dataset/prueba> dct:relation " + "[ dct:relation " * 65 + "1" + " ]" * 65 + " .",
    ],
    ids=["nodos-en-blanco", "colecciones", "limite"],
)
def test_deeply_nested_turtle_is_a_422(
    client: TestClient, editor_headers: dict[str, str], store: MemoryStore, tail: str
) -> None:
    response = _post(client, editor_headers, MINIMAL + tail + "\n")
    assert response.status_code == 422, response.text
    assert response.json()["kind"] == "syntax"
    assert user_graphs(store) == set()


def test_blank_node_nesting_and_lists_within_limits_are_fine() -> None:
    from app import ingest

    nested = "[ <urn:x:p> " * 10 + "1" + " ]" * 10
    long_list = "(" + " ".join(str(i) for i in range(500)) + ")"
    cycle = "_:a <urn:x:p> _:b . _:b <urn:x:p> _:a ."
    text = f"<urn:x:s> <urn:x:p> {nested} . <urn:x:s> <urn:x:q> {long_list} . {cycle}"
    ingest.check_terms(Graph().parse(data=text, format="turtle"))


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
