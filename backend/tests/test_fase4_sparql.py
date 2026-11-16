"""Fase 4: SPARQL público (decisión 42) y consultas guardadas (decisión 43)."""

import json
from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import sparql_public
from app.config import Settings
from app.models import AuditAction, AuditEvent, Role, User
from app.sparql_public import MemoryQueryRunner
from app.triplestore import MemoryStore
from tests.conftest import BASE_URI

SELECT = "SELECT ?s WHERE { ?s a <http://www.w3.org/ns/dcat#DatasetSeries> } ORDER BY ?s"
JSON_ACCEPT = {"Accept": "application/sparql-results+json, text/turtle;q=0.9"}


@pytest.fixture
def member(make_user: Callable[..., User], login: Callable[..., dict[str, str]]):
    make_user("socia", Role.MIEMBRO)
    return login("socia")


# --- Validación --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "INSERT DATA { <http://a> <http://b> <http://c> }",
        "DELETE WHERE { ?s ?p ?o }",
        "DROP ALL",
        "LOAD <http://ejemplo.org/x>",
        "CLEAR DEFAULT",
    ],
)
def test_updates_are_rejected(client: TestClient, query: str, query_runner) -> None:
    response = client.get("/sparql", params={"query": query})
    assert response.status_code == 400
    assert "solo lectura" in response.json()["detail"]
    assert query_runner.queries == []


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * WHERE { SERVICE <http://169.254.169.254/> { ?s ?p ?o } }",
        "SELECT * WHERE { ?a ?b ?c OPTIONAL { SERVICE SILENT <http://x/> { ?s ?p ?o } } }",
        "ASK { { SELECT * WHERE { SERVICE <http://x/> { ?s ?p ?o } } } }",
    ],
)
def test_service_is_rejected(client: TestClient, query: str, query_runner) -> None:
    response = client.post(
        "/sparql", content=query, headers={"Content-Type": "application/sparql-query"}
    )
    assert response.status_code == 400
    assert "SERVICE" in response.json()["detail"]
    assert query_runner.queries == []


def test_from_outside_repository_is_rejected(client: TestClient) -> None:
    bad = "SELECT * FROM <http://ejemplo.org/g> WHERE { ?s ?p ?o }"
    assert client.get("/sparql", params={"query": bad}).status_code == 400
    named = "PREFIX x: <http://ejemplo.org/> SELECT * FROM NAMED x:g WHERE { ?s ?p ?o }"
    assert client.get("/sparql", params={"query": named}).status_code == 400
    # Un grafo del repositorio sí se admite (aquí solo se valida: el doble en memoria de
    # rdflib intentaría descargar la IRI de FROM, Fuseki no).
    ok = f"SELECT * FROM <{BASE_URI}catalogo> WHERE {{ ?s ?p ?o }} LIMIT 1"  # noqa: S608
    assert sparql_public.validate(ok, BASE_URI).kind == "SELECT"


def test_syntax_error_is_readable(client: TestClient) -> None:
    response = client.get("/sparql", params={"query": "SELECT ?s WHERE { ?s ?p "})
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail.startswith("Error de sintaxis SPARQL")
    assert "Traceback" not in detail and "pyparsing" not in detail


def test_too_large_is_413(client: TestClient) -> None:
    big = "SELECT * WHERE { ?s ?p ?o } #" + "x" * 21_000
    assert client.get("/sparql", params={"query": big}).status_code == 413
    response = client.post(
        "/sparql", content=big, headers={"Content-Type": "application/sparql-query"}
    )
    assert response.status_code == 413


def test_unsupported_content_type(client: TestClient) -> None:
    response = client.post("/sparql", content=SELECT, headers={"Content-Type": "text/plain"})
    assert response.status_code == 415


# --- Ejecución y formatos ------------------------------------------------------------------


def test_select_json_and_csv(loaded_store: MemoryStore, client: TestClient) -> None:
    response = client.get("/sparql", params={"query": SELECT}, headers=JSON_ACCEPT)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/sparql-results+json")
    body = response.json()
    assert body["head"]["vars"] == ["s"]
    assert f"{BASE_URI}dataset/modbus-tcp-testbed" in [
        b["s"]["value"] for b in body["results"]["bindings"]
    ]
    csv = client.get("/sparql", params={"query": SELECT}, headers={"Accept": "text/csv"})
    assert csv.status_code == 200
    assert csv.text.splitlines()[0] == "s"


def test_form_post_and_default_format(loaded_store: MemoryStore, client: TestClient) -> None:
    response = client.post("/sparql", data={"query": "ASK { ?s ?p ?o }"})
    assert response.status_code == 200
    assert response.json() == {"head": {}, "boolean": True}


def test_construct_turtle_and_jsonld(loaded_store: MemoryStore, client: TestClient) -> None:
    query = "CONSTRUCT { ?s a ?t } WHERE { ?s a ?t } LIMIT 3"
    turtle = client.post(
        "/sparql",
        content=query,
        headers={"Content-Type": "application/sparql-query"} | JSON_ACCEPT,
    )
    assert turtle.status_code == 200
    assert turtle.headers["content-type"].startswith("text/turtle")
    jsonld = client.get(
        "/sparql", params={"query": query}, headers={"Accept": "application/ld+json"}
    )
    assert jsonld.status_code == 200
    json.loads(jsonld.text)


def test_not_acceptable(client: TestClient) -> None:
    response = client.get("/sparql", params={"query": SELECT}, headers={"Accept": "text/turtle"})
    assert response.status_code == 406


def test_truncation(loaded_store: MemoryStore, client: TestClient, settings: Settings) -> None:
    settings.sparql_max_rows = 2
    response = client.get("/sparql", params={"query": "SELECT * WHERE { ?s ?p ?o }"})
    assert response.headers["x-result-truncated"] == "true"
    assert len(response.json()["results"]["bindings"]) == 2
    construct = client.get("/sparql", params={"query": "CONSTRUCT WHERE { ?s ?p ?o }"})
    assert construct.headers["x-result-truncated"] == "true"
    small = client.get("/sparql", params={"query": "ASK { ?s ?p ?o }"})
    assert "x-result-truncated" not in small.headers


def test_union_default_graph_like_fuseki(loaded_store: MemoryStore, client: TestClient) -> None:
    query = "SELECT (COUNT(*) AS ?n) WHERE { ?c a <http://www.w3.org/2004/02/skos/core#Concept> }"
    body = client.get("/sparql", params={"query": query}).json()
    assert int(body["results"]["bindings"][0]["n"]["value"]) > 0


def test_cors_exposes_headers(client: TestClient) -> None:
    response = client.get(
        "/sparql", params={"query": "ASK {}"}, headers={"Origin": "http://localhost:5173"}
    )
    exposed = response.headers["access-control-expose-headers"]
    for name in ("X-Result-Truncated", "Retry-After", "Content-Disposition"):
        assert name in exposed


# --- Límite de frecuencia --------------------------------------------------------------------


def test_rate_limit_anonymous_ignores_forwarded_for(client: TestClient, settings: Settings) -> None:
    settings.sparql_rate_anon_per_min = 3
    for _ in range(3):
        assert client.get("/sparql", params={"query": "ASK {}"}).status_code == 200
    response = client.get(
        "/sparql", params={"query": "ASK {}"}, headers={"X-Forwarded-For": "203.0.113.9"}
    )
    assert response.status_code == 429
    assert 1 <= int(response.headers["retry-after"]) <= 60


def test_rate_limit_authenticated_is_per_user(
    client: TestClient, settings: Settings, member
) -> None:
    settings.sparql_rate_anon_per_min = 1
    settings.sparql_rate_auth_per_min = 2
    assert client.get("/sparql", params={"query": "ASK {}"}).status_code == 200
    assert client.get("/sparql", params={"query": "ASK {}"}).status_code == 429
    for _ in range(2):
        assert client.get("/sparql", params={"query": "ASK {}"}, headers=member).status_code == 200
    assert client.get("/sparql", params={"query": "ASK {}"}, headers=member).status_code == 429


# --- Fuseki (cliente HTTP) ------------------------------------------------------------------


def _runner(handler: Callable[[httpx.Request], httpx.Response]):
    return sparql_public.FusekiQueryRunner(
        "http://fuseki.test:3030", "itot", transport=httpx.MockTransport(handler)
    )


def test_fuseki_runner_truncates_construct_stream() -> None:
    lines = "".join(f"<http://a/{i}> <http://b> <http://c> .\n" for i in range(50))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/itot/query"
        assert request.headers["accept"] == "application/n-triples"
        return httpx.Response(200, text=lines)

    query = sparql_public.validate("CONSTRUCT WHERE { ?s ?p ?o }", BASE_URI)
    result = _runner(handler).run(query, max_rows=10, timeout=5)
    assert result.truncated and len(result.graph) == 10


def test_fuseki_runner_select_and_errors() -> None:
    data = {
        "head": {"vars": ["s"]},
        "results": {"bindings": [{"s": {"type": "uri", "value": "http://a"}}] * 5},
    }
    query = sparql_public.validate("SELECT ?s WHERE { ?s ?p ?o }", BASE_URI)
    result = _runner(lambda r: httpx.Response(200, json=data)).run(query, max_rows=3, timeout=5)
    assert result.truncated and len(result.bindings) == 3

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("lento", request=request)

    with pytest.raises(sparql_public.SparqlTimeoutError):
        _runner(timeout).run(query, max_rows=3, timeout=5)
    with pytest.raises(sparql_public.SparqlTimeoutError):
        _runner(lambda r: httpx.Response(503)).run(query, max_rows=3, timeout=5)
    with pytest.raises(sparql_public.SparqlBackendError):
        _runner(lambda r: httpx.Response(500)).run(query, max_rows=3, timeout=5)


def test_timeout_maps_to_504(
    client: TestClient, query_runner: MemoryQueryRunner, monkeypatch
) -> None:
    def slow(*_args, **_kwargs):
        raise sparql_public.SparqlTimeoutError()

    monkeypatch.setattr(query_runner, "run", slow)
    assert client.get("/sparql", params={"query": "ASK {}"}).status_code == 504


# --- Consultas guardadas --------------------------------------------------------------------


def test_reference_queries_are_listed_and_run(
    loaded_store: MemoryStore, client: TestClient
) -> None:
    response = client.get("/sparql/queries")
    assert response.status_code == 200
    queries = response.json()
    assert [q["id"] for q in queries] == ["mapeos", "ot-datasets", "sin-definicion"]
    ot = queries[1]
    assert ot["kind"] == "reference"
    assert ot["title"] == "Datasets clasificados en OT"
    assert ot["hint"] == "dcat:theme dentro del esquema OT / ICS"
    assert "{BASE_URI}" not in ot["query"] and f"<{BASE_URI}vocab/ot>" in ot["query"]
    assert "# title:" not in ot["query"]
    for query in queries:
        run = client.post("/sparql", data={"query": query["query"]})
        assert run.status_code == 200, (query["id"], run.text)


def test_personal_queries_crud(client: TestClient, member, make_user, login, db: Session) -> None:
    body = {"title": "Mía", "hint": "pista", "query": "ASK {}"}
    assert client.post("/sparql/queries", json=body).status_code == 401
    created = client.post("/sparql/queries", json=body, headers=member)
    assert created.status_code == 201
    item = created.json()
    assert item["kind"] == "personal" and item["created_at"]
    listed = client.get("/sparql/queries", headers=member).json()
    assert listed[-1]["id"] == item["id"]
    assert all(q["kind"] == "reference" for q in client.get("/sparql/queries").json())

    make_user("otra", Role.EDITOR)
    other = login("otra")
    assert client.put(f"/sparql/queries/{item['id']}", json=body, headers=other).status_code == 404
    assert client.delete(f"/sparql/queries/{item['id']}", headers=other).status_code == 404
    assert item["id"] not in [q["id"] for q in client.get("/sparql/queries", headers=other).json()]

    changed = client.put(
        f"/sparql/queries/{item['id']}", json=body | {"title": "Cambiada"}, headers=member
    )
    assert changed.status_code == 200 and changed.json()["title"] == "Cambiada"
    assert client.put("/sparql/queries/ot-datasets", json=body, headers=member).status_code == 404
    assert client.delete("/sparql/queries/ot-datasets", headers=member).status_code == 404
    assert client.delete(f"/sparql/queries/{item['id']}", headers=member).status_code == 204

    actions = [e.action for e in db.scalars(select(AuditEvent))]
    assert AuditAction.SAVED_QUERY_CREATED.value in actions
    assert AuditAction.SAVED_QUERY_DELETED.value in actions
    for event in db.scalars(select(AuditEvent)):
        assert "ASK {}" not in json.dumps(event.details)


def test_saved_query_limits(client: TestClient, member, settings: Settings) -> None:
    settings.saved_queries_max_per_user = 1
    body = {"title": "Una", "query": "ASK {}"}
    assert client.post("/sparql/queries", json=body, headers=member).status_code == 201
    assert client.post("/sparql/queries", json=body, headers=member).status_code == 409
    for bad in (
        {"title": "", "query": "ASK {}"},
        {"title": "x" * 121, "query": "ASK {}"},
        {"title": "t", "query": ""},
        {"title": "t", "query": "x" * 20_481},
        {"title": "t\x00", "query": "ASK {}"},
    ):
        assert client.post("/sparql/queries", json=bad, headers=member).status_code == 422
