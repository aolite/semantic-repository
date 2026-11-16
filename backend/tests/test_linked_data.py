"""Negociación de contenido en las URIs persistentes ``/dataset/{slug}[/{version}]``."""

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, URIRef
from rdflib.namespace import RDF

from app.triplestore import MemoryStore
from app.uris import DCAT
from tests.conftest import BASE_URI

MODBUS = f"{BASE_URI}dataset/modbus-tcp-testbed"
BROWSER = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


@pytest.fixture
def api(client: TestClient, loaded_store: MemoryStore) -> TestClient:
    return client


@pytest.mark.parametrize("accept", ["", "*/*"])
def test_series_uri_without_rdf_accept_redirects(api: TestClient, accept: str) -> None:
    response = api.get(
        "/dataset/modbus-tcp-testbed", headers={"Accept": accept}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith("/datasets/modbus-tcp-testbed")


@pytest.mark.parametrize(
    ("accept", "media", "fmt"),
    [
        ("text/turtle", "text/turtle", "turtle"),
        ("application/ld+json", "application/ld+json", "json-ld"),
        # Fase 4 (decisión 31): sin Accept o con */* ya no sale Turtle sino un 303 al HTML
        # (ver test_series_uri_without_rdf_accept_redirects).
    ],
)
def test_series_uri_returns_rdf(api: TestClient, accept: str | None, media: str, fmt: str) -> None:
    headers = {"Accept": accept} if accept else {}
    response = api.get("/dataset/modbus-tcp-testbed", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(media)
    assert "Accept" in response.headers["vary"]
    graph = Graph().parse(data=response.text, format=fmt)
    assert (URIRef(MODBUS), RDF.type, DCAT.DatasetSeries) in graph
    # La serie incluye todas sus versiones.
    versions = set(graph.subjects(DCAT.inSeries, URIRef(MODBUS)))
    assert len(versions) == 3


def test_version_uri_returns_version_rdf(api: TestClient) -> None:
    response = api.get(
        "/dataset/modbus-tcp-testbed/2.0.0", headers={"Accept": "application/ld+json"}
    )
    assert response.status_code == 200
    graph = Graph().parse(data=response.text, format="json-ld")
    assert (URIRef(f"{MODBUS}/2.0.0"), DCAT.version, None) in graph
    assert (URIRef(f"{MODBUS}/2.1.0"), None, None) not in graph


def test_html_redirects_303_to_frontend(api: TestClient) -> None:
    response = api.get(
        "/dataset/modbus-tcp-testbed", headers={"Accept": BROWSER}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "http://localhost:5173/datasets/modbus-tcp-testbed"
    assert "Accept" in response.headers["vary"]

    response = api.get(
        "/dataset/modbus-tcp-testbed/2.0.0",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == (
        "http://localhost:5173/datasets/modbus-tcp-testbed?version=2.0.0"
    )


def test_frontend_base_url_is_configurable(
    loaded_store: MemoryStore, monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "frontend_base_url", "https://catalogo.example.org")
    response = client.get(
        "/dataset/modbus-tcp-testbed", headers={"Accept": "text/html"}, follow_redirects=False
    )
    assert (
        response.headers["location"] == "https://catalogo.example.org/datasets/modbus-tcp-testbed"
    )


def test_not_acceptable(api: TestClient) -> None:
    response = api.get("/dataset/modbus-tcp-testbed", headers={"Accept": "application/pdf"})
    assert response.status_code == 406


@pytest.mark.parametrize(
    "path",
    ["/dataset/no-existe", "/dataset/modbus-tcp-testbed/9.9.9", "/dataset/no-existe/1.0.0"],
)
def test_unknown_resources_are_404_even_for_html(api: TestClient, path: str) -> None:
    for accept in ("text/turtle", "text/html"):
        response = api.get(path, headers={"Accept": accept}, follow_redirects=False)
        assert response.status_code == 404


@pytest.mark.parametrize(
    "path",
    ["/dataset/Mal_Slug", "/dataset/modbus-tcp-testbed/2.1", "/dataset/modbus-tcp-testbed/v2.1.0"],
)
def test_invalid_segments_are_422(api: TestClient, loaded_store: MemoryStore, path: str) -> None:
    assert api.get(path).status_code == 422
    assert loaded_store.queries == []
