"""Cliente de Fuseki (``FusekiStore``) contra un servidor simulado con ``httpx.MockTransport``."""

import base64

import httpx
import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.compare import isomorphic

from app.config import Settings
from app.triplestore import FusekiStore, TriplestoreConfigError, TriplestoreError

GRAPH = "https://semantic.example.org/itot/dataset/prueba"
NT = f'<{GRAPH}> <http://purl.org/dc/terms/title> "Prueba" .\n'


def _store(handler, credentials=("backend", "clave-ficticia")) -> FusekiStore:
    return FusekiStore(
        "http://fuseki.test:3030",
        "itot",
        credentials=credentials,
        timeout_seconds=2,
        transport=httpx.MockTransport(handler),
    )


def test_construct_posts_to_query_without_credentials() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=NT, headers={"Content-Type": "application/n-triples"})

    graph = _store(handler).construct("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")
    assert (URIRef(GRAPH), None, Literal("Prueba")) in graph
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == "http://fuseki.test:3030/itot/query"
    assert "authorization" not in request.headers
    assert request.headers["accept"] == "application/n-triples"


def test_put_graph_uses_graph_store_with_basic_auth() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201)

    graph = Graph().parse(data=NT, format="nt")
    _store(handler).put_graph(GRAPH, graph)
    request = seen[0]
    assert request.method == "PUT"
    assert request.url.path == "/itot/data"
    assert request.url.params["graph"] == GRAPH
    expected = base64.b64encode(b"backend:clave-ficticia").decode()
    assert request.headers["authorization"] == f"Basic {expected}"
    assert request.headers["content-type"].startswith("application/n-triples")
    assert isomorphic(Graph().parse(data=request.content.decode(), format="nt"), graph)


def test_write_without_credentials_fails_clearly() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - no se llama
        raise AssertionError("no debería llegar a Fuseki")

    with pytest.raises(TriplestoreConfigError, match="FUSEKI_USER y FUSEKI_PASSWORD"):
        _store(handler, credentials=None).put_graph(GRAPH, Graph())


@pytest.mark.parametrize("code", [401, 403])
def test_rejected_credentials(code: int) -> None:
    store = _store(lambda request: httpx.Response(code))
    with pytest.raises(TriplestoreConfigError, match="FUSEKI_USER"):
        store.put_graph(GRAPH, Graph())


def test_server_error_and_timeout() -> None:
    with pytest.raises(TriplestoreError, match="500"):
        _store(lambda request: httpx.Response(500)).construct("CONSTRUCT {} WHERE {}")

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("lento", request=request)

    with pytest.raises(TriplestoreError, match="ReadTimeout"):
        _store(timeout).construct("CONSTRUCT {} WHERE {}")


def test_put_graph_rejects_unsafe_graph_iri() -> None:
    store = _store(lambda request: httpx.Response(201))
    with pytest.raises(ValueError):
        store.put_graph("https://x.example/a> } DROP ALL", Graph())


def test_from_settings_reads_credentials_and_timeout(settings: Settings) -> None:
    settings = settings.model_copy(
        update={"fuseki_user": "u", "fuseki_password": "p", "fuseki_timeout_seconds": 7.5}
    )
    store = FusekiStore.from_settings(settings)
    assert store._credentials == ("u", "p")
    assert store._timeout.read == 7.5
    assert store._timeout.connect == 3.0
    assert store._endpoint == "http://fuseki.test:3030/itot"
