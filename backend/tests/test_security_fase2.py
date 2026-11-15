"""Pruebas de seguridad de la fase 2 (agente ``qa``): catálogo, ingesta y triplestore.

Complementan ``test_catalog.py``, ``test_ingest.py``, ``test_linked_data.py``,
``test_sparql.py`` y ``test_triplestore.py`` con cuatro bloques:

1. **Inyección SPARQL** en ``q``, ``domain``, ``slug``, ``version``, ``format``, la cabecera
   ``Accept`` y el contenido de la ingesta, más una comprobación estática de que ninguna
   consulta se construye fuera de ``app.sparql``.
2. **Ingesta maliciosa**: escribir fuera de la serie, contextos JSON-LD remotos (SSRF),
   tamaño, anidamiento extremo, ``Content-Type`` falso y permisos por rol con auditoría.
3. **Credenciales de Fuseki**: que no salgan en respuestas, logs, ``repr`` ni OpenAPI.
4. **Lectura pública**: que solo se lean los grafos de las series publicadas.

Los hallazgos QA-G2-01 a QA-G2-04 de la revisión de la fase 2 ya están corregidos y sus
pruebas pasan sin marca. Un defecto nuevo se marcaría con ``xfail(strict=True)`` y su
identificador ``QA-G2-nn`` hasta que el agente dueño lo corrija.

Todas las credenciales de este fichero son ficticias. Ninguna prueba sale a la red.
"""

import ast
import base64
import json
import logging
import re
import socket
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from rdflib import BNode, Graph, URIRef
from rdflib import Literal as RdfLiteral
from rdflib.compare import isomorphic
from rdflib.namespace import RDF
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import catalog
from app.config import Settings, get_settings
from app.deps import get_triplestore
from app.models import AuditAction, AuditEvent, Role, User
from app.sparql import iri, literal, render
from app.triplestore import FusekiStore, MemoryStore
from app.uris import DCAT, DCT, SKOS, Uris
from tests.conftest import BASE_URI

TURTLE = {"Content-Type": "text/turtle"}
JSONLD = {"Content-Type": "application/ld+json"}

MODBUS = f"{BASE_URI}dataset/modbus-tcp-testbed"
PRUEBA = f"{BASE_URI}dataset/prueba"
PUBLIC = "http://publications.europa.eu/resource/authority/access-right/PUBLIC"

# Serie mínima válida. No usa datos del prototipo: son textos de relleno de la prueba.
MINIMAL = f"""
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct:  <http://purl.org/dc/terms/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix sh:   <http://www.w3.org/ns/shacl#> .
<dataset/prueba> a dcat:DatasetSeries ;
    dct:title "Serie de prueba"@es ; dct:description "Descripción"@es ;
    dcat:last <dataset/prueba/1.0.0> .
<dataset/prueba/1.0.0> a dcat:Dataset ;
    dct:title "Serie de prueba"@es ; dct:description "Descripción"@es ;
    dcat:version "1.0.0" ; dcat:inSeries <dataset/prueba> ;
    dct:accessRights <{PUBLIC}> ;
    dcat:distribution <dataset/prueba/1.0.0/csv> .
<dataset/prueba/1.0.0/csv> a dcat:Distribution ;
    dcat:accessURL <dataset/prueba/1.0.0/csv> .
"""

# Credenciales ficticias de Fuseki: lo que nunca debe aparecer en una respuesta o un log.
FUSEKI_TEST_USER = "usuario-fuseki-ficticio"
FUSEKI_TEST_PASSWORD = "clave-fuseki-ficticia-7f3a9c"
FUSEKI_TEST_BASIC = base64.b64encode(f"{FUSEKI_TEST_USER}:{FUSEKI_TEST_PASSWORD}".encode()).decode()


# --- Utilidades y fixtures -------------------------------------------------------------


@pytest.fixture
def api(client: TestClient, loaded_store: MemoryStore) -> TestClient:
    """Cliente con los datos sintéticos de G2 ya cargados."""
    return client


@pytest.fixture
def lenient(client: TestClient) -> TestClient:
    """Mismo backend, pero un error interno se devuelve como 500 en lugar de relanzarse."""
    return TestClient(client.app, raise_server_exceptions=False)


@pytest.fixture
def editor_headers(
    make_user: Callable[..., User], login: Callable[..., dict[str, str]]
) -> dict[str, str]:
    make_user("pub", Role.EDITOR)
    return login("pub")


@pytest.fixture
def no_network(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Bloquea toda salida a la red y devuelve la lista de intentos.

    Depende de ``client`` para instalarse después de que arranque el bucle de eventos del
    cliente de pruebas, que habla con la aplicación en memoria, sin sockets de red.
    """
    attempts: list[str] = []

    def _blocked(name: str) -> Callable[..., None]:
        def _raise(*args: object, **_kwargs: object) -> None:
            attempts.append(f"{name}{args[-1:]!r}"[:200])
            raise OSError("red bloqueada por la prueba")

        return _raise

    monkeypatch.setattr(socket.socket, "connect", _blocked("connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked("connect_ex"))
    monkeypatch.setattr(socket, "create_connection", _blocked("create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", _blocked("getaddrinfo"))
    monkeypatch.setattr(urllib.request, "urlopen", _blocked("urlopen"))
    return attempts


def _post(
    client: TestClient, headers: dict[str, str], body: str | bytes, ctype: dict[str, str] = TURTLE
) -> httpx.Response:
    content = body.encode() if isinstance(body, str) else body
    return client.post("/datasets", content=content, headers=headers | ctype)


def _minimal_graph() -> Graph:
    return Graph().parse(data=MINIMAL, format="turtle", publicID=BASE_URI)


def _snapshot(store: MemoryStore) -> dict[str, Graph]:
    """Copia de todos los grafos con nombre (para comprobar después que no cambian)."""
    result: dict[str, Graph] = {}
    for name in sorted(store.graph_names()):
        copy = Graph()
        for triple in store.dataset.graph(URIRef(name)):
            copy.add(triple)
        result[name] = copy
    return result


def _assert_unchanged(store: MemoryStore, before: dict[str, Graph]) -> None:
    after = _snapshot(store)
    assert set(after) == set(before), set(after) ^ set(before)
    for name, graph in before.items():
        assert isomorphic(graph, after[name]), f"ha cambiado el grafo {name}"


def _published_events(session_factory: sessionmaker[Session]) -> list[AuditEvent]:
    with session_factory() as session:
        return list(
            session.scalars(
                select(AuditEvent).where(AuditEvent.action == AuditAction.DATASET_PUBLISHED)
            )
        )


_SERIES_IRI = re.compile(re.escape(f"<{BASE_URI}dataset/") + r"[a-z0-9]+(-[a-z0-9]+)*>")


def _assert_only_fixed_queries(store: MemoryStore) -> None:
    """Toda consulta enviada al triplestore es una plantilla fija; lo único variable es la
    IRI de un grafo de serie, que sigue el patrón de slug."""
    uris = Uris(BASE_URI)
    fixed = {
        render(
            catalog.CATALOG_QUERY,
            dataset_ns=literal(uris.dataset_ns),
            vocab=iri(uris.vocab_graph),
        ),
        catalog.SERIES_GRAPH_QUERY,
        # El grafo del vocabulario es fijo (sale de BASE_URI); el de la serie, variable.
        catalog.THEME_LABELS_QUERY.replace("$vocab", iri(uris.vocab_graph).text),
        "CONSTRUCT { ?s ?p ?o } WHERE { GRAPH $graph { ?s ?p ?o } }",
    }
    for query in store.queries:
        normalized, _count = _SERIES_IRI.subn("$graph", query)
        assert normalized in fixed, f"consulta inesperada:\n{query}"


# Cargas de inyección: cierran literales, IRIs y bloques, comentan el resto o intentan
# una actualización. Ninguna debe llegar a una consulta ni cambiar el triplestore.
INJECTIONS = [
    '" } UNION { GRAPH ?g { ?s ?p ?o } } #',
    "' } UNION { ?s ?p ?o } #",
    '""" } UNION { ?s ?p ?o } #',
    "> } UNION { GRAPH ?g { ?s ?p ?o } } #",
    "} ; DROP ALL ; #",
    "; INSERT DATA { GRAPH <urn:x:g> { <urn:x:s> <urn:x:p> <urn:x:o> } } #",
    "\\u0022 } UNION { ?s ?p ?o } #",
    "\\U00000022 } UNION { ?s ?p ?o } #",
    "\\",
    '\\"',
    "$dataset_ns",
    "$graph ${graph} $$",
    "modbus\n} UNION { ?s ?p ?o } #",
    "modbus\r\n#",
    "modbus\x00",
    "\u2028} UNION { ?s ?p ?o }",
    "{{}}{}%s%(x)s{0}",
    "SERVICE <http://127.0.0.1:9/sparql> { ?s ?p ?o }",
    "LOAD <file:///etc/passwd>",
]


# --- 1. Inyección SPARQL ---------------------------------------------------------------


@pytest.mark.parametrize("q", INJECTIONS)
def test_q_never_reaches_sparql(api: TestClient, loaded_store: MemoryStore, q: str) -> None:
    before = _snapshot(loaded_store)
    response = api.get("/datasets", params={"q": q})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 0
    assert all(q not in query for query in loaded_store.queries)
    _assert_only_fixed_queries(loaded_store)
    _assert_unchanged(loaded_store, before)


def test_q_too_long_is_rejected_before_querying(api: TestClient, loaded_store: MemoryStore) -> None:
    response = api.get("/datasets", params={"q": "a" * 201})
    assert response.status_code == 422
    assert loaded_store.queries == []


def test_validation_errors_do_not_echo_the_payload(api: TestClient) -> None:
    payload = "x } UNION { ?s ?p ?o }"
    for path, params in (
        ("/datasets", {"domain": payload}),
        ("/datasets", {"q": payload * 20}),
        ("/datasets/modbus-tcp-testbed", {"version": payload}),
        ("/datasets/modbus-tcp-testbed/rdf", {"format": payload}),
    ):
        response = api.get(path, params=params)
        assert response.status_code == 422, path
        assert "UNION" not in response.text, path


@pytest.mark.parametrize("domain", [*INJECTIONS, "OT", "ot ", " ot", "ot,it", "ot\n", "*", ""])
def test_domain_only_accepts_the_four_slugs(
    api: TestClient, loaded_store: MemoryStore, domain: str
) -> None:
    response = api.get("/datasets", params={"domain": domain})
    assert response.status_code == 422, response.text
    assert loaded_store.queries == []


SLUG_INJECTIONS = [
    "modbus-tcp-testbed%0A",
    "modbus-tcp-testbed%0D%0A",
    "modbus-tcp-testbed%00",
    "modbus-tcp-testbed%20",
    "%20modbus-tcp-testbed",
    "modbus-tcp-testbed%3E",
    "modbus-tcp-testbed%3E%20%7D%20UNION%20%7B%20GRAPH%20%3Fg%20%7B%20%3Fs%20%3Fp%20%3Fo%20%7D",
    "modbus-tcp-testbed%22",
    "modbus-tcp-testbed%5C",
    "modbus-tcp-testbed%23",
    "modbus-tcp-testbed%3Fx",
    "modbus-tcp-testbed%7B%7D",
    "modbus-tcp-testbed%7C",
    "modbus-tcp-testbed%5E",
    "modbus-tcp-testbed%60",
    "%24graph",
    "..%2Fvocab",
    "%2E%2E",
    "..%2F..%2Fcatalogo",
    "Modbus-Tcp-Testbed",
    "modbus_tcp_testbed",
    "modbus--tcp",
    "-modbus",
    "modbus-",
    "m%C3%B3dbus",
    "%EF%BD%8Dodbus",  # una m de ancho completo (U+FF4D)
    "a" * 201,
]


@pytest.mark.parametrize("slug", SLUG_INJECTIONS)
def test_slug_is_validated_in_every_route(
    api: TestClient, loaded_store: MemoryStore, lenient: TestClient, slug: str
) -> None:
    before = _snapshot(loaded_store)
    for path in (
        f"/datasets/{slug}",
        f"/datasets/{slug}/rdf",
        f"/dataset/{slug}",
        f"/dataset/{slug}/2.1.0",
    ):
        response = lenient.get(path, headers={"Accept": "text/turtle"})
        assert response.status_code in (404, 422), f"{path}: {response.status_code}"
    assert loaded_store.queries == []
    _assert_unchanged(loaded_store, before)


VERSION_INJECTIONS = [
    "2.1.0%0A",
    "2.1.0%20",
    "2.1.0%3E",
    "2.1.0%22%20%7D%20UNION%20%7B%20%3Fs%20%3Fp%20%3Fo%20%7D%20%23",
    "2.1.0%23",
    "2.1",
    "2.1.0.0",
    "v2.1.0",
    "02.1.0",
    "2.1.0-rc.1",
    "%EF%BC%92.1.0",  # un 2 de ancho completo (U+FF12)
    "%D9%A2.1.0",  # dígito arábigo-índico: \d lo aceptaría, [0-9] no
    "1" * 51,
]


@pytest.mark.parametrize("version", VERSION_INJECTIONS)
def test_version_is_validated_in_query_and_path(
    api: TestClient, loaded_store: MemoryStore, lenient: TestClient, version: str
) -> None:
    for path in (
        f"/datasets/modbus-tcp-testbed?version={version}",
        f"/datasets/modbus-tcp-testbed/rdf?version={version}",
        f"/dataset/modbus-tcp-testbed/{version}",
    ):
        response = lenient.get(path)
        assert response.status_code in (404, 422), f"{path}: {response.status_code}"
    assert loaded_store.queries == []


@pytest.mark.parametrize(
    "rdf_format",
    ["turtle%0A", "TURTLE", "json-ld", "n-quads", "trig", "rdfxml", "turtle%20", "turtle,jsonld"],
)
def test_format_only_accepts_the_two_values(
    api: TestClient, loaded_store: MemoryStore, rdf_format: str
) -> None:
    response = api.get(f"/datasets/modbus-tcp-testbed/rdf?format={rdf_format}")
    assert response.status_code == 422
    assert loaded_store.queries == []


@pytest.mark.parametrize(
    "params",
    [
        {"page": "0"},
        {"page": "-1"},
        {"page": "10001"},
        {"page": "1e3"},
        {"page": "1 OR 1=1"},
        {"page_size": "0"},
        {"page_size": "101"},
        {"page_size": "99999999999999999999"},
        {"page_size": "20; DROP ALL"},
    ],
)
def test_pagination_is_bounded(
    api: TestClient, loaded_store: MemoryStore, params: dict[str, str]
) -> None:
    assert api.get("/datasets", params=params).status_code == 422
    assert loaded_store.queries == []


ACCEPT_INJECTIONS = [
    'text/turtle" } UNION { ?s ?p ?o } #',
    "text/turtle; q=1 } UNION { GRAPH ?g { ?s ?p ?o } }",
    "text/turtle;q=nan",
    "text/turtle;q=inf",
    "text/turtle;q=-inf",
    "text/turtle;q=1e400",
    "text/turtle;q=",
    "text/turtle;q",
    ";;;;",
    ",,,,",
    "/",
    "*",
    "text/",
    "/turtle",
    "<http://x/> ; DROP ALL",
    "application/sparql-update",
    "text/html\tDROP",
    "text/turtle, " * 2000,
    "a/b;q=0.5;" * 2000,
]


@pytest.mark.parametrize("accept", ACCEPT_INJECTIONS)
def test_accept_header_is_only_negotiated(
    api: TestClient, loaded_store: MemoryStore, lenient: TestClient, accept: str
) -> None:
    before = _snapshot(loaded_store)
    for path in (
        "/datasets/modbus-tcp-testbed/rdf",
        "/dataset/modbus-tcp-testbed",
        "/dataset/modbus-tcp-testbed/2.1.0",
    ):
        response = lenient.get(path, headers={"Accept": accept}, follow_redirects=False)
        assert response.status_code in (200, 303, 406), f"{path}: {response.status_code}"
        if response.status_code == 200:
            assert response.headers["content-type"].split(";")[0] in (
                "text/turtle",
                "application/ld+json",
            )
        if response.status_code == 303:
            assert response.headers["location"].startswith(
                get_settings().frontend_base_url + "/datasets/modbus-tcp-testbed"
            )
    _assert_only_fixed_queries(loaded_store)
    _assert_unchanged(loaded_store, before)


def test_redirect_target_is_fixed_by_configuration(api: TestClient) -> None:
    """El 303 solo puede ir a FRONTEND_BASE_URL: ni Host ni X-Forwarded-* lo cambian."""
    response = api.get(
        "/dataset/modbus-tcp-testbed/2.1.0",
        headers={
            "Accept": "text/html",
            "Host": "atacante.example",
            "X-Forwarded-Host": "atacante.example",
            "X-Forwarded-Proto": "https",
            "Referer": "https://atacante.example/",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == (
        f"{get_settings().frontend_base_url}/datasets/modbus-tcp-testbed?version=2.1.0"
    )


def test_every_public_read_uses_only_fixed_queries(
    api: TestClient, loaded_store: MemoryStore
) -> None:
    for path in (
        "/datasets",
        "/datasets?q=modbus&domain=ot",
        "/datasets/modbus-tcp-testbed",
        "/datasets/modbus-tcp-testbed?version=1.0.0",
        "/datasets/modbus-tcp-testbed/rdf?format=jsonld",
        "/dataset/modbus-tcp-testbed",
        "/dataset/modbus-tcp-testbed/2.0.0",
    ):
        assert api.get(path).status_code == 200, path
    assert loaded_store.queries
    _assert_only_fixed_queries(loaded_store)


def _app_sources() -> list[Path]:
    return sorted((Path(catalog.__file__).parent).rglob("*.py"))


def test_no_query_is_built_outside_app_sparql() -> None:
    """Comprobación estática de todos los puntos donde se construyen consultas.

    - Lo que se pasa a ``.construct(...)`` sale de ``render(...)`` o de ``_graph_query(...)``.
    - El único f-string con sintaxis SPARQL es el de ``triplestore._graph_query``, que
      inserta la IRI con ``app.sparql.iri``.
    - Nadie usa ``.format`` ni ``%`` sobre una plantilla de consulta.
    """
    keywords = re.compile(r"\b(CONSTRUCT|SELECT|ASK|DESCRIBE|INSERT|DELETE|WHERE|GRAPH)\b")
    fstrings: list[str] = []
    for path in _app_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions = {
            child: node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            for child in ast.walk(node)
        }
        for node in ast.walk(tree):
            where = f"{path.name}:{getattr(node, 'lineno', '?')}"
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "construct"
            ):
                assert len(node.args) == 1 and not node.keywords, where
                arg = node.args[0]
                assert isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name), where
                assert arg.func.id in {"render", "_graph_query"}, where
            if isinstance(node, ast.JoinedStr):
                text = "".join(
                    v.value
                    for v in node.values
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)
                )
                if keywords.search(text) and "{" in text:
                    fstrings.append(f"{path.name}:{functions.get(node, '<módulo>')}")
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
                left = node.left
                if isinstance(left, ast.Constant) and isinstance(left.value, str):
                    assert not keywords.search(left.value), where
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "format"
                and isinstance(node.func.value, ast.Constant)
                and isinstance(node.func.value.value, str)
            ):
                assert not keywords.search(node.func.value.value), where
    assert fstrings == ["triplestore.py:_graph_query"], fstrings


def test_query_templates_take_only_escaped_terms() -> None:
    """Las plantillas solo tienen los marcadores previstos y ``render`` exige términos."""
    assert set(re.findall(r"\$[a-z_]+", catalog.CATALOG_QUERY)) == {"$dataset_ns", "$vocab"}
    assert set(re.findall(r"\$[a-z_]+", catalog.SERIES_GRAPH_QUERY)) == {"$graph"}
    assert set(re.findall(r"\$[a-z_]+", catalog.THEME_LABELS_QUERY)) == {"$graph", "$vocab"}
    with pytest.raises(TypeError):
        render(catalog.SERIES_GRAPH_QUERY, graph="<urn:x:g> } UNION { ?s ?p ?o")  # type: ignore[arg-type]


# Literales hostiles dentro del RDF de la ingesta: se guardan tal cual, como datos.
STORED_PAYLOADS = [
    'Título" } UNION { GRAPH ?g { ?s ?p ?o } } # fin',
    "Título' ; DROP ALL ; INSERT DATA { <urn:x:s> <urn:x:p> <urn:x:o> } #",
    "Línea 1\nLínea 2\r\n} UNION { ?s ?p ?o }\t#",
    'Barra \\ y comillas \\" y llaves {} {{ }} $graph ${dataset_ns}',
    "<script>alert(1)</script> & <img src=x onerror=alert(1)>",
    "\"\"\" triple comilla ''' @es ^^<urn:x:tipo>",
]


@pytest.mark.parametrize("payload", STORED_PAYLOADS)
def test_hostile_literals_in_ingest_are_stored_as_data(
    api: TestClient,
    loaded_store: MemoryStore,
    editor_headers: dict[str, str],
    payload: str,
) -> None:
    before = _snapshot(loaded_store)
    graph = _minimal_graph()
    version = URIRef(f"{PRUEBA}/1.0.0")
    for subject in (URIRef(PRUEBA), version):
        graph.set((subject, DCT.title, RdfLiteral(payload, lang="es")))
    graph.add((version, DCAT.keyword, RdfLiteral(payload, lang="es")))
    response = _post(api, editor_headers, graph.serialize(format="turtle"))
    assert response.status_code == 201, response.text

    loaded_store.queries.clear()
    detail = api.get("/datasets/prueba")
    assert detail.status_code == 200
    assert detail.json()["title"] == payload
    assert detail.json()["version"]["keywords"] == [payload]
    listing = api.get("/datasets").json()
    assert listing["total"] == 4
    assert payload in {item["title"] for item in listing["items"]}
    # El RDF devuelto contiene el mismo literal, en los dos formatos.
    for rdf_format, parser in (("turtle", "turtle"), ("jsonld", "json-ld")):
        text = api.get(f"/datasets/prueba/rdf?format={rdf_format}").text
        returned = Graph().parse(data=text, format=parser)
        assert (version, DCT.title, RdfLiteral(payload, lang="es")) in returned
    # Buscar por el propio texto encuentra solo esa serie, y nada de ello llega a SPARQL.
    found = api.get("/datasets", params={"q": payload}).json()
    assert [item["slug"] for item in found["items"]] == ["prueba"]
    assert all(payload not in query for query in loaded_store.queries)
    _assert_only_fixed_queries(loaded_store)
    # El resto de grafos sigue igual.
    after = _snapshot(loaded_store)
    assert set(after) == set(before) | {PRUEBA}
    for name, old in before.items():
        assert isomorphic(old, after[name]), name


# IRIs que SPARQL (IRIREF) y N-Triples no admiten. rdflib las deja pasar al analizar el
# Turtle; si se guardan, o rompen la escritura en Fuseki o rompen la lectura posterior.
BAD_OBJECT_IRIS = [
    "<http://x.example/a b>",
    "<http://x.example/{}|^`>",
    "<http://x.example/a\\u000Ab>",
    "<http://x.example/a\\u0009b>",
]


@pytest.mark.parametrize("bad", BAD_OBJECT_IRIS)
def test_ingest_rejects_iris_with_forbidden_characters(
    lenient: TestClient, store: MemoryStore, editor_headers: dict[str, str], bad: str
) -> None:
    body = MINIMAL + f"<dataset/prueba> dct:relation {bad} .\n"
    response = _post(lenient, editor_headers, body)
    assert response.status_code == 422, response.text
    assert store.graph_names() == set()


def test_published_series_can_always_be_read_back(
    lenient: TestClient, store: MemoryStore, editor_headers: dict[str, str]
) -> None:
    body = MINIMAL + "<dataset/prueba> dct:relation <http://x.example/a b> .\n"
    _post(lenient, editor_headers, body)
    if PRUEBA not in store.graph_names():
        return  # rechazada en la ingesta: nada que leer
    for path in ("/datasets/prueba", "/datasets/prueba/rdf", "/dataset/prueba"):
        response = lenient.get(path, headers={"Accept": "text/turtle"})
        assert response.status_code == 200, f"{path}: {response.status_code}"


def test_body_sent_to_fuseki_has_one_triple_per_line(
    lenient: TestClient, editor_headers: dict[str, str]
) -> None:
    """Lo que el backend envía a Fuseki debe ser N-Triples bien formado: una línea por
    triple. Una IRI con ``\\n`` parte la línea (hoy Fuseki rechazaría la escritura)."""
    bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            bodies.append(request.content.decode("utf-8"))
            return httpx.Response(201)
        return httpx.Response(200, text="", headers={"Content-Type": "application/n-triples"})

    lenient.app.dependency_overrides[get_triplestore] = lambda: FusekiStore(
        "http://fuseki.test:3030",
        "itot",
        credentials=(FUSEKI_TEST_USER, FUSEKI_TEST_PASSWORD),
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    body = MINIMAL + "<dataset/prueba> dct:relation <http://x.example/a\\u000Ab> .\n"
    response = _post(lenient, editor_headers, body)
    assert response.status_code in (201, 422), response.text
    for sent in bodies:
        for line in sent.splitlines():
            assert line.endswith(" ."), f"línea N-Triples partida: {line!r}"


# --- 2. Ingesta maliciosa --------------------------------------------------------------

FOREIGN_SUBJECTS = [
    # Otra serie publicada
    '<dataset/modbus-tcp-testbed> dct:title "Secuestrada"@es .',
    '<dataset/modbus-tcp-testbed/2.1.0> dct:title "Secuestrada"@es .',
    '<dataset/modbus-tcp-testbed/2.1.0/pcap> dct:title "Secuestrada"@es .',
    "<dataset/modbus-tcp-testbed> dcat:last <dataset/prueba/1.0.0> .",
    # Prefijo parecido al de la propia serie, pero de otra
    '<dataset/prueba-otra> dct:title "Otra"@es .',
    '<dataset/pruebax/1.0.0> dct:title "Otra"@es .',
    # El catálogo
    "<catalogo> dcat:dataset <dataset/prueba> .",
    '<catalogo> dct:title "Catálogo secuestrado"@es .',
    # El vocabulario
    '<vocab/ot/modbus-tcp> skos:prefLabel "Etiqueta falsa"@es .',
    '<vocab/ot> skos:prefLabel "Dominio falso"@es .',
    "<vocab/tipo-dataset/sintetico> a skos:Concept .",
    # La propia base y otros espacios bajo BASE_URI
    '<> dct:title "Raíz"@es .',
    '<shapes#Dataset-title> sh:deactivated "true"^^<http://www.w3.org/2001/XMLSchema#boolean> .',
    '<ontologia/itot> dct:title "Ontología"@es .',
    # IRIs ajenas a BASE_URI
    '<https://otro.example/x> dct:title "Ajeno"@es .',
    '<http://www.w3.org/ns/dcat#Dataset> dct:title "DCAT"@es .',
    f'<{PUBLIC}> skos:prefLabel "Restringido"@es .',
    '<urn:x:recurso> dct:title "URN"@es .',
    '<file:///etc/passwd> dct:title "Fichero"@es .',
    # Dominio parecido a BASE_URI
    '<https://semantic.example.org.atacante.example/itot/dataset/prueba/x> dct:title "X"@es .',
    '<https://semantic.example.org/itot-otro/dataset/prueba/x> dct:title "X"@es .',
    '<http://semantic.example.org/itot/dataset/prueba/x> dct:title "X"@es .',
]


@pytest.mark.parametrize("extra", FOREIGN_SUBJECTS)
@pytest.mark.parametrize("rdf_format", ["turtle", "json-ld"])
def test_ingest_cannot_write_outside_its_series(
    api: TestClient,
    loaded_store: MemoryStore,
    editor_headers: dict[str, str],
    session_factory: sessionmaker[Session],
    extra: str,
    rdf_format: str,
) -> None:
    before = _snapshot(loaded_store)
    body = MINIMAL + extra + "\n"
    ctype = TURTLE
    if rdf_format == "json-ld":
        graph = Graph().parse(data=body, format="turtle", publicID=BASE_URI)
        body = graph.serialize(format="json-ld")
        ctype = JSONLD
    response = _post(api, editor_headers, body, ctype)
    assert response.status_code == 422, response.text
    assert response.json()["kind"] == "uri"
    _assert_unchanged(loaded_store, before)
    assert _published_events(session_factory) == []


@pytest.mark.parametrize(
    "extra",
    [
        # Una versión o una segunda serie descritas con un nodo en blanco
        "[] a dcat:Dataset ; dcat:inSeries <dataset/modbus-tcp-testbed> ; dcat:version '9.9.9' ;"
        f" dct:title 'X'@es ; dct:description 'X'@es ; dct:accessRights <{PUBLIC}> .",
        "[] a dcat:DatasetSeries ; dct:title 'X'@es ; dct:description 'X'@es .",
        # Una versión propia que dice pertenecer a otra serie
        "<dataset/prueba/1.0.0> dcat:inSeries <dataset/modbus-tcp-testbed> .",
        # Una versión propia con un número de versión que no es el de su URI
        "<dataset/prueba/1.0.0> dcat:version '9.9.9' .",
        # Una distribución de otra serie colgada de una versión propia
        "<dataset/prueba/1.0.0> dcat:distribution <dataset/modbus-tcp-testbed/2.1.0/pcap> .",
    ],
)
def test_ingest_cannot_attach_itself_to_another_series(
    api: TestClient, loaded_store: MemoryStore, editor_headers: dict[str, str], extra: str
) -> None:
    before = _snapshot(loaded_store)
    response = _post(api, editor_headers, MINIMAL + extra + "\n")
    assert response.status_code == 422, response.text
    assert response.json()["kind"] in {"uri", "structure", "shacl"}
    _assert_unchanged(loaded_store, before)


def test_json_ld_named_graph_cannot_target_another_graph(
    api: TestClient, loaded_store: MemoryStore, editor_headers: dict[str, str]
) -> None:
    """Un ``@graph`` con nombre (otra serie, el catálogo o el vocabulario) no se escribe."""
    before = _snapshot(loaded_store)
    base = json.loads(_minimal_graph().serialize(format="json-ld"))
    for target in (MODBUS, f"{BASE_URI}catalogo", f"{BASE_URI}vocab/"):
        document = [
            *base,
            {
                "@id": target,
                "@graph": [
                    {"@id": MODBUS, "http://purl.org/dc/terms/title": [{"@value": "Secuestrada"}]}
                ],
            },
        ]
        response = _post(api, editor_headers, json.dumps(document), JSONLD)
        assert response.status_code in (200, 201, 422), response.text
        after = _snapshot(loaded_store)
        for name, graph in before.items():
            assert isomorphic(graph, after[name]), f"{target} ha cambiado {name}"
        stored = after.get(PRUEBA, Graph())
        assert "Secuestrada" not in {str(o) for o in stored.objects()}
        assert not list(stored.triples((URIRef(MODBUS), None, None)))


def test_valid_ingest_only_touches_its_own_graph(
    api: TestClient, loaded_store: MemoryStore, editor_headers: dict[str, str]
) -> None:
    before = _snapshot(loaded_store)
    assert _post(api, editor_headers, MINIMAL).status_code == 201
    after = _snapshot(loaded_store)
    assert set(after) == set(before) | {PRUEBA}
    for name, graph in before.items():
        assert isomorphic(graph, after[name]), name
    assert isomorphic(after[PRUEBA], _minimal_graph())


def test_network_guard_detects_a_remote_context(no_network: list[str]) -> None:
    """Control positivo: sin la defensa de la ingesta, rdflib sí descargaría el contexto.
    Si esto deja de cumplirse, las pruebas de SSRF de abajo ya no demostrarían nada."""
    with pytest.raises(Exception):  # noqa: B017 - cualquier fallo de red sirve
        Graph().parse(
            data='{"@context": "http://127.0.0.1:9/contexto.jsonld", "@id": "urn:x:a"}',
            format="json-ld",
        )
    assert no_network


def _jsonld_with(context: object, **extra: object) -> str:
    return json.dumps({"@context": context, "@id": PRUEBA, **extra})


REMOTE_JSONLD = [
    _jsonld_with("http://127.0.0.1:9/contexto.jsonld"),
    _jsonld_with("http://169.254.169.254/latest/meta-data/"),
    _jsonld_with("http://fuseki:3030/$/datasets"),
    _jsonld_with("file:///etc/passwd"),
    _jsonld_with("contexto.jsonld"),
    _jsonld_with("//127.0.0.1:9/contexto.jsonld"),
    _jsonld_with(["http://127.0.0.1:9/a.jsonld", {"dct": "http://purl.org/dc/terms/"}]),
    _jsonld_with([{"dct": "http://purl.org/dc/terms/"}, ["http://127.0.0.1:9/a.jsonld"]]),
    _jsonld_with({"@import": "http://127.0.0.1:9/a.jsonld"}),
    _jsonld_with({"@version": 1.1, "@import": "a.jsonld"}),
    # Contexto con ámbito dentro de la definición de un término
    _jsonld_with({"x": {"@id": "http://x.example/p", "@context": "http://127.0.0.1:9/a.jsonld"}}),
    _jsonld_with({"x": {"@id": "http://x.example/p", "@context": ["http://127.0.0.1:9/a"]}}),
    # Contexto en un nodo anidado, en @graph y en una lista
    _jsonld_with({"p": "http://x.example/p"}, p={"@context": "http://127.0.0.1:9/a.jsonld"}),
    _jsonld_with({"p": "http://x.example/p"}, p=[{"@context": ["http://127.0.0.1:9/a"]}]),
    json.dumps({"@graph": [{"@context": "http://127.0.0.1:9/a.jsonld", "@id": PRUEBA}]}),
    json.dumps([{"@context": "http://127.0.0.1:9/a.jsonld", "@id": PRUEBA}]),
    json.dumps(
        {"@id": PRUEBA, "http://x.example/p": {"@list": [{"@context": "http://127.0.0.1:9/a"}]}}
    ),
]


@pytest.mark.parametrize("document", REMOTE_JSONLD)
def test_json_ld_remote_contexts_never_leave_the_server(
    client: TestClient,
    store: MemoryStore,
    editor_headers: dict[str, str],
    no_network: list[str],
    document: str,
) -> None:
    response = _post(client, editor_headers, document, JSONLD)
    assert no_network == [], no_network
    assert response.status_code == 422, response.text
    assert "contextos remotos" in response.json()["detail"]
    assert "root:" not in response.text
    assert store.graph_names() == set()


INDIRECT_FETCHES = [
    # Alias de @context (JSON-LD no lo permite; no debe tratarse como contexto)
    (
        JSONLD,
        json.dumps(
            {
                "@context": {"ctx": "@context", "dct": "http://purl.org/dc/terms/"},
                "@id": PRUEBA,
                "ctx": "http://127.0.0.1:9/a.jsonld",
            }
        ),
    ),
    # @base y @vocab remotos: son prefijos, no documentos que descargar
    (
        JSONLD,
        json.dumps(
            {
                "@context": {"@base": "http://127.0.0.1:9/", "@vocab": "http://127.0.0.1:9/v#"},
                "@id": "dataset/prueba",
                "titulo": "x",
            }
        ),
    ),
    # owl:imports y sh:shapesGraph en los datos: pyshacl no debe seguirlos
    (TURTLE, MINIMAL + "[] a owl:Ontology ; owl:imports <http://127.0.0.1:9/onto.ttl> .\n"),
    (TURTLE, MINIMAL + "<dataset/prueba> owl:imports <http://127.0.0.1:9/onto.ttl> .\n"),
    (TURTLE, MINIMAL + "<dataset/prueba> sh:shapesGraph <http://127.0.0.1:9/shapes.ttl> .\n"),
    # Propiedades con URL: se guardan como datos, no se visitan
    (
        TURTLE,
        MINIMAL
        + "<dataset/prueba/1.0.0/csv> dcat:downloadURL <http://169.254.169.254/latest/> .\n"
        + "<dataset/prueba/1.0.0> dct:conformsTo <http://127.0.0.1:9/esquema> ;\n"
        + "    dcat:landingPage <http://fuseki:3030/$/server> .\n",
    ),
]


@pytest.mark.parametrize(("ctype", "document"), INDIRECT_FETCHES)
def test_ingest_never_fetches_urls_found_in_the_data(
    client: TestClient,
    lenient: TestClient,
    editor_headers: dict[str, str],
    no_network: list[str],
    ctype: dict[str, str],
    document: str,
) -> None:
    response = _post(lenient, editor_headers, document, ctype)
    assert no_network == [], no_network
    assert response.status_code in (201, 422), response.text
    if response.status_code == 201:
        for path in ("/datasets", "/datasets/prueba", "/datasets/prueba/rdf", "/dataset/prueba"):
            assert lenient.get(path).status_code == 200, path
        assert no_network == [], no_network


@pytest.fixture
def small_limit(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> int:
    limit = len(MINIMAL.encode()) + 10
    monkeypatch.setattr(settings, "ingest_max_bytes", limit)
    return limit


def test_body_at_the_limit_is_accepted_and_one_byte_more_is_not(
    small_limit: int, client: TestClient, store: MemoryStore, editor_headers: dict[str, str]
) -> None:
    exact = MINIMAL.encode() + b" " * 10
    assert len(exact) == small_limit
    too_big = exact + b" "
    rejected = _post(client, editor_headers, too_big)
    assert rejected.status_code == 413
    assert store.graph_names() == set()
    assert _post(client, editor_headers, exact).status_code == 201


def test_streamed_body_without_content_length_is_cut_at_the_limit(
    small_limit: int, client: TestClient, store: MemoryStore, editor_headers: dict[str, str]
) -> None:
    """Sin ``Content-Length`` (envío por trozos) el límite se aplica al leer."""
    sent = 0

    def chunks() -> Iterator[bytes]:
        nonlocal sent
        yield MINIMAL.encode()
        for _ in range(1000):
            sent += 1
            yield b"# " + b"x" * 1000 + b"\n"

    response = client.post("/datasets", content=chunks(), headers=editor_headers | TURTLE)
    assert "content-length" not in {k.lower() for k in response.request.headers}
    assert response.status_code == 413
    assert store.graph_names() == set()


def test_oversized_body_is_rejected_before_parsing(
    small_limit: int,
    client: TestClient,
    editor_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import ingest

    def _must_not_parse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("se ha intentado analizar un cuerpo demasiado grande")

    monkeypatch.setattr(ingest, "parse_rdf", _must_not_parse)
    response = _post(client, editor_headers, MINIMAL + "# " + "x" * 5000)
    assert response.status_code == 413
    assert "x" * 50 not in response.text


def test_default_ingest_limit_is_ten_megabytes() -> None:
    assert Settings.model_fields["ingest_max_bytes"].default == 10 * 1024 * 1024


DEPTH = 100_000


@pytest.mark.parametrize(
    "document",
    [
        "[" * DEPTH + "]" * DEPTH,
        '{"a":' * DEPTH + "1" + "}" * DEPTH,
        '{"@context":{"p":"http://x.example/p"},"@id":"'
        + PRUEBA
        + '","p":'
        + '{"p":' * 5000
        + "1"
        + "}" * 5000
        + "}",
    ],
    ids=["listas", "objetos", "nodos-anidados"],
)
def test_deeply_nested_json_ld_is_a_422(
    lenient: TestClient, store: MemoryStore, editor_headers: dict[str, str], document: str
) -> None:
    response = _post(lenient, editor_headers, document, JSONLD)
    assert response.status_code == 422, response.status_code
    assert store.graph_names() == set()


@pytest.mark.parametrize(
    "tail",
    [
        "<dataset/prueba> dct:relation " + "[ dct:relation " * 20_000 + "1" + " ]" * 20_000 + " .",
        "<dataset/prueba> dct:relation " + "(" * 20_000 + ")" * 20_000 + " .",
    ],
    ids=["nodos-en-blanco", "colecciones"],
)
def test_deeply_nested_turtle_is_a_422(
    lenient: TestClient, store: MemoryStore, editor_headers: dict[str, str], tail: str
) -> None:
    response = _post(lenient, editor_headers, MINIMAL + tail)
    assert response.status_code == 422, response.status_code
    assert response.json()["kind"] == "syntax"
    assert store.graph_names() == set()


def test_ingest_errors_have_a_bounded_size(
    lenient: TestClient, editor_headers: dict[str, str]
) -> None:
    """Un error de sintaxis no devuelve el documento entero al cliente."""
    body = "<dataset/prueba> <http://x.example/p> " + '"' + "A" * 200_000
    response = _post(lenient, editor_headers, body)
    assert response.status_code == 422
    assert len(response.content) < 2_000


def test_xml_entity_bomb_is_not_parsed_as_xml(
    lenient: TestClient, store: MemoryStore, editor_headers: dict[str, str]
) -> None:
    """RDF/XML no se admite: una bomba de entidades no llega a ningún analizador XML."""
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;">'
        '<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">&c;&xxe;</rdf:RDF>'
    )
    for ctype in ("application/rdf+xml", "application/xml", "text/xml"):
        response = lenient.post(
            "/datasets", content=bomb.encode(), headers=editor_headers | {"Content-Type": ctype}
        )
        assert response.status_code == 415, ctype
    for ctype in (TURTLE, JSONLD):
        response = _post(lenient, editor_headers, bomb, ctype)
        assert response.status_code == 422
        assert "root:" not in response.text
    assert store.graph_names() == set()


@pytest.mark.parametrize(
    "ctype",
    [
        None,
        "",
        "text/plain",
        "application/json",
        "application/octet-stream",
        "application/x-www-form-urlencoded",
        "multipart/form-data; boundary=x",
        "application/sparql-update",
        "application/sparql-query",
        "application/n-triples",
        "application/n-quads",
        "application/trig",
        "application/rdf+xml",
        "text/turtle-star",
        "text/turtlex",
        "xtext/turtle",
        "text/turtle,application/sparql-update",
        "*/*",
    ],
)
def test_other_content_types_are_415(
    client: TestClient, store: MemoryStore, editor_headers: dict[str, str], ctype: str | None
) -> None:
    headers = dict(editor_headers)
    if ctype is not None:
        headers["Content-Type"] = ctype
    response = client.post("/datasets", content=MINIMAL.encode(), headers=headers)
    assert response.status_code == 415, response.text
    assert store.graph_names() == set()


def test_sparql_update_disguised_as_turtle_is_not_executed(
    api: TestClient, loaded_store: MemoryStore, editor_headers: dict[str, str]
) -> None:
    before = _snapshot(loaded_store)
    for body in (
        "DROP ALL",
        "CLEAR GRAPH <" + MODBUS + ">",
        "INSERT DATA { GRAPH <" + MODBUS + "> { <urn:x:s> <urn:x:p> <urn:x:o> } }",
        "DELETE WHERE { GRAPH ?g { ?s ?p ?o } }",
    ):
        for ctype in (TURTLE, JSONLD):
            response = _post(api, editor_headers, body, ctype)
            assert response.status_code == 422, body
            assert response.json()["kind"] == "syntax"
    _assert_unchanged(loaded_store, before)


def test_declared_format_decides_the_parser(
    client: TestClient, store: MemoryStore, editor_headers: dict[str, str]
) -> None:
    """El cuerpo se analiza con el formato declarado: no se adivina por el contenido."""
    as_jsonld = _minimal_graph().serialize(format="json-ld")
    wrong_1 = _post(client, editor_headers, MINIMAL, JSONLD)
    wrong_2 = _post(client, editor_headers, as_jsonld, TURTLE)
    for response in (wrong_1, wrong_2):
        assert response.status_code == 422, response.text
        assert response.json()["kind"] == "syntax"
    assert store.graph_names() == set()


@pytest.mark.parametrize(
    ("ctype", "encoding", "expected"),
    [
        ("TEXT/Turtle ; charset=UTF-8", "utf-8", 201),
        ("text/turtle; charset=utf-16", "utf-16", 422),
        ("text/turtle; charset=utf-8", "utf-16", 422),
        ("text/turtle; charset=latin-1", "latin-1", 422),
    ],
)
def test_only_utf8_bodies_are_accepted(
    client: TestClient,
    editor_headers: dict[str, str],
    ctype: str,
    encoding: str,
    expected: int,
) -> None:
    response = client.post(
        "/datasets",
        content=MINIMAL.encode(encoding),
        headers=editor_headers | {"Content-Type": ctype},
    )
    assert response.status_code == expected, response.text


# Permisos y auditoría


@pytest.mark.parametrize(
    ("role", "expected"),
    [(Role.MIEMBRO, 403), (Role.EDITOR, 201), (Role.ADMIN, 201)],
)
def test_ingest_by_role_and_audit(
    client: TestClient,
    store: MemoryStore,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
    session_factory: sessionmaker[Session],
    role: Role,
    expected: int,
) -> None:
    user = make_user("autor", role)
    response = _post(client, login("autor"), MINIMAL)
    assert response.status_code == expected, response.text
    events = _published_events(session_factory)
    if expected == 403:
        assert events == []
        assert store.graph_names() == set()
        return
    assert store.graph_names() == {PRUEBA}
    assert len(events) == 1
    event = events[0]
    assert event.actor_id == user.id
    assert event.actor_username == "autor"
    assert event.details == {
        "series": PRUEBA,
        "slug": "prueba",
        "graph": PRUEBA,
        "versions": ["1.0.0"],
        "triples": len(_minimal_graph()),
        "created": True,
        "changed": True,
        "via": "api",
    }


def test_anonymous_and_bad_tokens_cannot_ingest(
    client: TestClient,
    store: MemoryStore,
    editor_headers: dict[str, str],
    session_factory: sessionmaker[Session],
) -> None:
    token = editor_headers["Authorization"].removeprefix("Bearer ")
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload}.{signature[:-2]}{'AA' if signature[-2:] != 'AA' else 'BB'}"
    for headers in (
        {},
        {"Authorization": "Bearer "},
        {"Authorization": "Bearer no-es-un-token"},
        {"Authorization": f"Bearer {tampered}"},
        {"Authorization": f"Bearer {header}.{payload}."},
        {"Authorization": f"Basic {FUSEKI_TEST_BASIC}"},
        {"Authorization": token},
    ):
        response = _post(client, headers, MINIMAL)
        assert response.status_code == 401, headers
    assert store.graph_names() == set()
    assert _published_events(session_factory) == []


def test_authentication_is_checked_before_the_body(small_limit: int, client: TestClient) -> None:
    wrong_type = client.post(
        "/datasets", content=MINIMAL.encode(), headers={"Content-Type": "text/plain"}
    )
    too_big = client.post("/datasets", content=b"#" * (small_limit + 1), headers=TURTLE)
    assert (wrong_type.status_code, too_big.status_code) == (401, 401)


def test_role_and_account_changes_apply_to_ingest_immediately(
    client: TestClient,
    store: MemoryStore,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
    db: Session,
) -> None:
    """Un token de editor vigente deja de servir si la cuenta baja de rol o se desactiva."""
    user = make_user("autor", Role.EDITOR)
    headers = login("autor")
    user.role = Role.MIEMBRO
    db.commit()
    assert _post(client, headers, MINIMAL).status_code == 403
    user.role = Role.EDITOR
    user.is_active = False
    db.commit()
    assert _post(client, headers, MINIMAL).status_code == 401
    assert store.graph_names() == set()


def test_rejected_ingests_leave_no_audit_event_and_no_data(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    store: MemoryStore,
    editor_headers: dict[str, str],
    session_factory: sessionmaker[Session],
) -> None:
    monkeypatch.setattr(settings, "ingest_max_bytes", len(MINIMAL.encode()) + 1000)
    without_title = MINIMAL.replace(
        '<dataset/prueba/1.0.0> a dcat:Dataset ;\n    dct:title "Serie de prueba"@es ;',
        "<dataset/prueba/1.0.0> a dcat:Dataset ;",
    )
    assert without_title != MINIMAL
    attempts = [
        (_post(client, editor_headers, "no es turtle <"), 422),
        (_post(client, editor_headers, without_title), 422),
        (_post(client, editor_headers, MINIMAL + '<catalogo> dct:title "X" .'), 422),
        (_post(client, editor_headers, MINIMAL + "# " + "x" * 5000), 413),
        (_post(client, editor_headers, MINIMAL, {"Content-Type": "text/plain"}), 415),
    ]
    for response, expected in attempts:
        assert response.status_code == expected, response.text
    assert store.graph_names() == set()
    assert _published_events(session_factory) == []


def test_only_get_and_post_exist_on_the_catalog(
    api: TestClient, loaded_store: MemoryStore, editor_headers: dict[str, str]
) -> None:
    """No hay borrado ni modificación parcial, ni un endpoint SPARQL en la fase 2."""
    before = _snapshot(loaded_store)
    for method in ("PUT", "PATCH", "DELETE"):
        for path in (
            "/datasets",
            "/datasets/modbus-tcp-testbed",
            "/datasets/modbus-tcp-testbed/rdf",
            "/dataset/modbus-tcp-testbed",
            "/dataset/modbus-tcp-testbed/2.1.0",
        ):
            response = api.request(method, path, headers=editor_headers)
            assert response.status_code == 405, f"{method} {path}"
    for path in ("/sparql", "/query", "/update", "/data", "/itot/sparql", "/itot/update"):
        for method in ("GET", "POST"):
            response = api.request(method, path, params={"query": "ASK {}"})
            assert response.status_code == 404, f"{method} {path}"
    _assert_unchanged(loaded_store, before)


# --- 3. Credenciales de Fuseki ---------------------------------------------------------


@pytest.fixture
def fuseki_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Entorno con credenciales (ficticias) de escritura en Fuseki."""
    monkeypatch.setenv("FUSEKI_USER", FUSEKI_TEST_USER)
    monkeypatch.setenv("FUSEKI_PASSWORD", FUSEKI_TEST_PASSWORD)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _leaks(text: str) -> list[str]:
    return [
        name
        for name, value in (
            ("usuario", FUSEKI_TEST_USER),
            ("contraseña", FUSEKI_TEST_PASSWORD),
            ("cabecera Basic", FUSEKI_TEST_BASIC),
        )
        if value in text
    ]


def test_settings_repr_and_errors_hide_fuseki_credentials(fuseki_env: None) -> None:
    settings = get_settings()
    assert settings.fuseki_write_credentials == (FUSEKI_TEST_USER, FUSEKI_TEST_PASSWORD)
    for text in (repr(settings), str(settings), repr(FusekiStore.from_settings(settings))):
        assert _leaks(text) == []


def test_openapi_and_health_do_not_expose_fuseki_credentials(
    fuseki_env: None, client: TestClient
) -> None:
    assert get_settings().fuseki_write_credentials is not None
    for path in ("/openapi.json", "/health", "/health/ready", "/docs"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert _leaks(response.text) == [], path
    schema = client.get("/openapi.json").text.lower()
    for word in ("fuseki_password", "fuseki_user", "fuseki_admin_password", "fuseki.test"):
        assert word not in schema, word


def test_committed_openapi_has_no_fuseki_settings() -> None:
    from app.export_openapi import OPENAPI_PATH

    text = OPENAPI_PATH.read_text(encoding="utf-8").lower()
    for word in ("fuseki_password", "fuseki_user", "fuseki_admin_password", "jwt_secret"):
        assert word not in text, word


def _fuseki_that(handler: Callable[[httpx.Request], httpx.Response]) -> FusekiStore:
    return FusekiStore(
        "http://fuseki.test:3030",
        "itot",
        credentials=(FUSEKI_TEST_USER, FUSEKI_TEST_PASSWORD),
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )


def _echo_everything(status: int) -> Callable[[httpx.Request], httpx.Response]:
    """Un Fuseki que falla y devuelve en el cuerpo todo lo que ha recibido."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method != "PUT":
            return httpx.Response(200, text="", headers={"Content-Type": "application/n-triples"})
        echoed = f"{request.url} {dict(request.headers)} {FUSEKI_TEST_PASSWORD}"
        return httpx.Response(status, text=echoed)

    return handler


def _network_failure(exc_type: type[httpx.HTTPError]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method != "PUT":
            return httpx.Response(200, text="", headers={"Content-Type": "application/n-triples"})
        raise exc_type(
            f"fallo hacia http://{FUSEKI_TEST_USER}:{FUSEKI_TEST_PASSWORD}@fuseki.test:3030/"
        )

    return handler


@pytest.mark.parametrize(
    "handler",
    [
        _echo_everything(400),
        _echo_everything(401),
        _echo_everything(403),
        _echo_everything(500),
        _echo_everything(503),
        _network_failure(httpx.ConnectError),
        _network_failure(httpx.ConnectTimeout),
        _network_failure(httpx.ReadTimeout),
    ],
    ids=["400", "401", "403", "500", "503", "sin-conexion", "timeout-conexion", "timeout-lectura"],
)
def test_fuseki_write_failures_do_not_leak_credentials(
    lenient: TestClient,
    editor_headers: dict[str, str],
    session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    lenient.app.dependency_overrides[get_triplestore] = lambda: _fuseki_that(handler)
    with caplog.at_level(logging.DEBUG):
        response = _post(lenient, editor_headers, MINIMAL)
    assert response.status_code == 503, response.text
    assert _leaks(response.text) == []
    assert _leaks(str(dict(response.headers))) == []
    assert "fuseki.test" not in response.text
    logged = "\n".join(
        f"{record.getMessage()} {record.exc_text or ''}" for record in caplog.records
    )
    assert _leaks(logged) == []
    # Una publicación que no ha ocurrido no deja evento de auditoría.
    assert _published_events(session_factory) == []


def test_successful_write_does_not_log_credentials(
    lenient: TestClient, editor_headers: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            seen.append(request.headers.get("authorization", ""))
            return httpx.Response(201)
        # Las lecturas van sin credenciales.
        assert "authorization" not in request.headers
        return httpx.Response(200, text="", headers={"Content-Type": "application/n-triples"})

    lenient.app.dependency_overrides[get_triplestore] = lambda: _fuseki_that(handler)
    with caplog.at_level(logging.DEBUG):
        response = _post(lenient, editor_headers, MINIMAL)
    assert response.status_code == 201, response.text
    assert seen == [f"Basic {FUSEKI_TEST_BASIC}"]
    assert _leaks(response.text) == []
    assert _leaks("\n".join(record.getMessage() for record in caplog.records)) == []


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"FUSEKI_USER": FUSEKI_TEST_USER},
        {"FUSEKI_USER": FUSEKI_TEST_USER, "FUSEKI_PASSWORD": ""},
        {"FUSEKI_PASSWORD": FUSEKI_TEST_PASSWORD},
    ],
    ids=["sin-nada", "sin-password", "password-vacia", "sin-usuario"],
)
def test_ingest_without_fuseki_password_fails_clearly_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    request: pytest.FixtureRequest,
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    request.addfinalizer(get_settings.cache_clear)
    # Las fixtures que dependen de la configuración se piden después de fijar el entorno.
    client: TestClient = request.getfixturevalue("client")
    editor_headers: dict[str, str] = request.getfixturevalue("editor_headers")
    session_factory: sessionmaker[Session] = request.getfixturevalue("session_factory")
    settings = get_settings()
    assert settings.fuseki_write_credentials is None

    requests: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        requests.append(req.method)
        return httpx.Response(200, text="", headers={"Content-Type": "application/n-triples"})

    client.app.dependency_overrides[get_triplestore] = lambda: FusekiStore.from_settings(
        settings, transport=httpx.MockTransport(handler)
    )
    response = _post(client, editor_headers, MINIMAL)
    assert response.status_code == 503, response.text
    detail = response.json()["detail"]
    # Error claro: nombra las variables que faltan...
    assert "FUSEKI_USER" in detail and "FUSEKI_PASSWORD" in detail
    # ...sin filtrar valores, la URL de Fuseki ni el contenido enviado.
    assert _leaks(response.text) == []
    assert settings.fuseki_url not in response.text
    assert "Serie de prueba" not in response.text
    # No se ha enviado nada a Fuseki ni se ha auditado una publicación.
    assert "PUT" not in requests
    assert _published_events(session_factory) == []
    # La lectura sigue funcionando sin credenciales.
    assert client.get("/datasets").status_code == 200


def test_fuseki_read_failure_is_a_503_without_internal_details(
    lenient: TestClient,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"java.lang.Exception at {request.url}")

    lenient.app.dependency_overrides[get_triplestore] = lambda: _fuseki_that(handler)
    for path in ("/datasets", "/datasets/modbus-tcp-testbed", "/dataset/modbus-tcp-testbed"):
        response = lenient.get(path)
        assert response.status_code == 503, path
        assert "java.lang" not in response.text
        assert "fuseki.test" not in response.text
        assert _leaks(response.text) == []


# --- 4. Lectura pública ----------------------------------------------------------------

PRIVATE_GRAPH = f"{BASE_URI}privado/borrador"
SECRET_TITLE = "Serie que no está publicada"
SECRET_LABEL = "Etiqueta de un grafo no publicado"


def _all_public_text(client: TestClient, slugs: list[str]) -> str:
    """Todo lo que un lector anónimo puede obtener de la API del catálogo."""
    parts = [client.get("/datasets", params={"page_size": 100}).text]
    for domain in ("it", "ot", "pqc", "ia"):
        parts.append(client.get("/datasets", params={"domain": domain}).text)
    for slug in slugs:
        for path in (
            f"/datasets/{slug}",
            f"/datasets/{slug}/rdf?format=turtle",
            f"/datasets/{slug}/rdf?format=jsonld",
            f"/dataset/{slug}",
        ):
            parts.append(client.get(path, headers={"Accept": "text/turtle"}).text)
    return "\n".join(parts)


PUBLISHED_SLUGS = [
    "ejemplos-adversarios-vision",
    "hallazgos-auditorias-intrusion",
    "modbus-tcp-testbed",
]


def test_fixture_catalog_has_the_three_synthetic_series(api: TestClient) -> None:
    listing = api.get("/datasets").json()
    assert [item["slug"] for item in listing["items"]] == PUBLISHED_SLUGS or sorted(
        item["slug"] for item in listing["items"]
    ) == PUBLISHED_SLUGS
    assert all(item["synthetic"] is True for item in listing["items"])


@pytest.mark.parametrize(
    "slug", ["catalogo", "vocab", "ot", "tipo-dataset", "sintetico", "privado"]
)
def test_non_dataset_graphs_cannot_be_addressed_by_slug(
    api: TestClient, loaded_store: MemoryStore, slug: str
) -> None:
    """El catálogo y el vocabulario viven en grafos que ninguna ruta puede nombrar: toda
    lectura por slug va al grafo ``{BASE_URI}dataset/{slug}``."""
    for path in (f"/datasets/{slug}", f"/datasets/{slug}/rdf", f"/dataset/{slug}"):
        assert api.get(path).status_code == 404, path
    for query in loaded_store.queries:
        assert f"<{BASE_URI}dataset/{slug}>" in query


def test_series_rdf_contains_only_triples_of_its_own_graph(
    api: TestClient, loaded_store: MemoryStore
) -> None:
    for slug in PUBLISHED_SLUGS:
        own = loaded_store.dataset.graph(URIRef(f"{BASE_URI}dataset/{slug}"))
        for path in (f"/dataset/{slug}", f"/datasets/{slug}/rdf"):
            text = api.get(path, headers={"Accept": "text/turtle"}).text
            returned = Graph().parse(data=text, format="turtle")
            assert len(returned) > 0
            # Los nodos en blanco cambian de identificador al serializar: se comparan
            # los triples sin ellos y, para los demás, solo que no haya de más.
            ground = [t for t in returned if not any(isinstance(n, BNode) for n in t)]
            assert ground
            assert all(triple in own for triple in ground), path
            assert len(returned) <= len(own), path


def _private_series_graph() -> Graph:
    """Una serie con URI de dataset guardada en un grafo que no es el de una serie."""
    text = MINIMAL.replace("dataset/prueba", "dataset/borrador-interno").replace(
        "Serie de prueba", SECRET_TITLE
    )
    return Graph().parse(data=text, format="turtle", publicID=BASE_URI)


def test_series_in_a_non_published_graph_is_not_readable_by_slug(
    api: TestClient, loaded_store: MemoryStore
) -> None:
    loaded_store.put_graph(PRIVATE_GRAPH, _private_series_graph())
    for path in (
        "/datasets/borrador-interno",
        "/datasets/borrador-interno/rdf",
        "/dataset/borrador-interno",
        "/dataset/borrador-interno/1.0.0",
    ):
        response = api.get(path)
        assert response.status_code == 404, path
        assert SECRET_TITLE not in response.text


def test_series_in_a_non_published_graph_is_not_listed(
    api: TestClient, loaded_store: MemoryStore
) -> None:
    loaded_store.put_graph(PRIVATE_GRAPH, _private_series_graph())
    listing = api.get("/datasets", params={"page_size": 100}).json()
    assert sorted(item["slug"] for item in listing["items"]) == PUBLISHED_SLUGS
    assert SECRET_TITLE not in _all_public_text(api, PUBLISHED_SLUGS)


def test_theme_labels_are_not_read_from_non_published_graphs(
    api: TestClient, loaded_store: MemoryStore, editor_headers: dict[str, str]
) -> None:
    """Una serie que pone como tema un recurso descrito en un grafo no publicado no debe
    servir para leer las etiquetas de ese recurso."""
    hidden = URIRef(f"{BASE_URI}interno/recurso-reservado")
    private = Graph()
    private.add((hidden, SKOS.prefLabel, RdfLiteral(SECRET_LABEL, lang="es")))
    private.add((hidden, SKOS.altLabel, RdfLiteral(SECRET_LABEL + " (alt)", lang="es")))
    loaded_store.put_graph(PRIVATE_GRAPH, private)

    body = MINIMAL + f"<dataset/prueba/1.0.0> dcat:theme <{hidden}> .\n"
    assert _post(api, editor_headers, body).status_code == 201
    assert SECRET_LABEL not in _all_public_text(api, [*PUBLISHED_SLUGS, "prueba"])
    # Tampoco como oráculo de búsqueda.
    assert api.get("/datasets", params={"q": SECRET_LABEL}).json()["total"] == 0


def test_published_series_cannot_redefine_vocabulary_labels(
    api: TestClient, loaded_store: MemoryStore, editor_headers: dict[str, str]
) -> None:
    """Las etiquetas de dominios y temas que ve el catálogo salen del vocabulario: una
    serie no puede cambiarlas (ver también test_ingest_cannot_write_outside_its_series)."""
    before = api.get("/datasets", params={"page_size": 100}).json()
    body = MINIMAL + "<dataset/prueba/1.0.0> dcat:theme <vocab/ot/modbus-tcp> .\n"
    assert _post(api, editor_headers, body).status_code == 201
    after = api.get("/datasets", params={"page_size": 100}).json()
    assert after["total"] == before["total"] + 1
    old = {item["slug"]: item for item in before["items"]}
    for item in after["items"]:
        if item["slug"] != "prueba":
            assert item == old[item["slug"]]
    mine = next(item for item in after["items"] if item["slug"] == "prueba")
    modbus = old["modbus-tcp-testbed"]
    assert mine["domain"] == modbus["domain"]
    assert mine["synthetic"] is False
    assert (URIRef(PRUEBA), RDF.type, DCAT.DatasetSeries) in loaded_store.dataset.graph(
        URIRef(PRUEBA)
    )
