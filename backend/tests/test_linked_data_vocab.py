"""URIs persistentes de ontologías y esquemas: negociación de contenido y 303 al frontend."""

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF

from app.triplestore import MemoryStore
from app.uris import SKOS
from tests.conftest import BASE_URI

FRONTEND = "http://localhost:5173"  # valor por defecto de FRONTEND_BASE_URL
ONTO = f"{BASE_URI}onto/itot"
OT = f"{BASE_URI}vocab/ot"
FORMATS = {
    "text/turtle": "turtle",
    "application/ld+json": "json-ld",
    "application/rdf+xml": "xml",
}


@pytest.fixture
def api(client: TestClient, vocab_store: MemoryStore) -> TestClient:
    return client


def _get(api: TestClient, path: str, accept: str | None) -> object:
    headers = {"Accept": accept} if accept else {}
    return api.get(path, headers=headers, follow_redirects=False)


@pytest.mark.parametrize("accept", [*FORMATS, None, "*/*"])
def test_ontology_uri_serves_current_version(api: TestClient, accept: str | None) -> None:
    response = _get(api, "/onto/itot", accept)
    assert response.status_code == 200
    media = accept if accept in FORMATS else "text/turtle"
    assert response.headers["content-type"].startswith(media)
    assert "Accept" in response.headers["vary"]
    graph = Graph().parse(data=response.text, format=FORMATS[media])
    assert (URIRef(ONTO), OWL.versionIRI, URIRef(f"{ONTO}/1.2.0")) in graph
    # Los términos ({ontología}#Término) se resuelven con la ontología.
    assert (URIRef(f"{ONTO}#Control"), RDF.type, OWL.Class) in graph


def test_ontology_version_uri(api: TestClient) -> None:
    response = _get(api, "/onto/itot/1.1.0", "text/turtle")
    graph = Graph().parse(data=response.text, format="turtle")
    assert (URIRef(ONTO), OWL.versionIRI, URIRef(f"{ONTO}/1.1.0")) in graph


@pytest.mark.parametrize(
    ("path", "location"),
    [
        ("/onto/itot", f"{FRONTEND}/ontologias/itot"),
        ("/onto/itot/1.1.0", f"{FRONTEND}/ontologias/itot?version=1.1.0"),
        ("/vocab/ot", f"{FRONTEND}/vocabularios/ot"),
        ("/vocab/ot/modbus-tcp", f"{FRONTEND}/vocabularios/ot?concepto=modbus-tcp"),
        ("/vocab/corp/trl", f"{FRONTEND}/vocabularios/corp/trl"),
        (
            "/vocab/corp/trl/trl-1",
            f"{FRONTEND}/vocabularios/corp/trl?concepto=trl-1",
        ),
        ("/vocab/dominio/ot", f"{FRONTEND}/vocabularios/dominio?concepto=ot"),
    ],
)
def test_html_redirects_to_frontend(api: TestClient, path: str, location: str) -> None:
    accept = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    response = _get(api, path, accept)
    assert response.status_code == 303
    assert response.headers["location"] == location
    assert "Accept" in response.headers["vary"]


def test_scheme_uri(api: TestClient) -> None:
    response = _get(api, "/vocab/ot", "application/ld+json")
    graph = Graph().parse(data=response.text, format="json-ld")
    assert (URIRef(OT), RDF.type, SKOS.ConceptScheme) in graph
    assert (URIRef(f"{OT}/modbus-tcp"), SKOS.inScheme, URIRef(OT)) in graph


def test_concept_uri_returns_only_the_concept(api: TestClient) -> None:
    response = _get(api, "/vocab/ot/modbus-tcp", "text/turtle")
    graph = Graph().parse(data=response.text, format="turtle")
    subjects = set(graph.subjects())
    assert subjects == {URIRef(f"{OT}/modbus-tcp")}
    assert (
        URIRef(f"{OT}/modbus-tcp"),
        SKOS.broader,
        URIRef(f"{OT}/protocolos-industriales"),
    ) in graph


def test_corp_concept_uri(api: TestClient) -> None:
    response = _get(api, "/vocab/corp/trl/trl-1", "text/turtle")
    assert response.status_code == 200
    assert "TRL 1" in response.text


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("/onto/no-existe", 404),
        ("/onto/itot/9.9.9", 404),
        ("/onto/externas", 404),
        ("/onto/itot/v1", 422),
        ("/vocab/no-existe", 404),
        ("/vocab/ot/no-existe", 404),
        ("/vocab/corp", 404),
        ("/vocab/corp/no-existe", 404),
        ("/vocab/corp/trl/no-existe", 404),
        ("/vocab/OT", 422),
    ],
)
def test_missing_resources(api: TestClient, path: str, status: int) -> None:
    # También con text/html: no se redirige a una ficha que no existe.
    assert _get(api, path, "text/html").status_code == status
    assert _get(api, path, "text/turtle").status_code == status


def test_not_acceptable(api: TestClient) -> None:
    assert _get(api, "/onto/itot", "image/png").status_code == 406
    assert _get(api, "/vocab/ot", "application/json").status_code == 406
